"""
RPA API 服务模块。
提供 HTTP API 接口，支持消息回调、MQTT队列集成和延迟处理。
"""

import asyncio
import logging
import threading
import time
from queue import Empty, Queue
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import httpx

from omni_bot_sdk.rpa.action_handlers import (
    RPAActionType,
    RecallMessageAction,
    SendTextMessageAction,
    SendFileAction,
    SendImageAction,
)
from omni_bot_sdk.weixin.message_classes import MessageType


class SendTextRequest(BaseModel):
    """发送文本消息请求"""
    recipient_name: str = Field(..., description="接收者名称（联系人或群名）")
    message: str = Field(..., description="消息内容")
    at_user_name: Optional[str] = Field(None, description="@用户名称（仅群聊有效）")


class SendFileRequest(BaseModel):
    """发送文件请求"""
    recipient_name: str = Field(..., description="接收者名称")
    file_path: str = Field(..., description="文件路径")


class RecallMessageRequest(BaseModel):
    """撤回消息请求"""
    contact_name: str = Field(..., description="联系人名称")
    message_text: Optional[str] = Field(None, description="要撤回的消息内容（精确匹配）")
    keyword: Optional[str] = Field(None, description="关键词（模糊匹配）")
    recall_latest: bool = Field(False, description="是否撤回最新消息")
    similarity: float = Field(0.6, ge=0.0, le=1.0, description="相似度阈值")


class APIResponse(BaseModel):
    """通用 API 响应"""
    success: bool = Field(..., description="操作是否成功")
    message: str = Field(..., description="响应消息")
    task_id: Optional[str] = Field(None, description="任务ID（用于跟踪）")
    data: Optional[dict] = Field(None, description="附加数据")


class APIMessage:
    """API消息封装类，用于延迟处理"""
    def __init__(
        self,
        action_type: str,
        action_data: dict,
        insert_time: float,
        task_id: str
    ):
        self.action_type = action_type
        self.action_data = action_data
        self.insert_time = insert_time
        self.task_id = task_id


class RPATaskQueue:
    """
    RPA 任务队列管理器。
    负责接收 API 请求并将其转换为 RPA 动作放入队列。
    """

    def __init__(
        self,
        rpa_task_queue: Queue,
        process_delay: int = 30,
        callback_url: str = "",
        mqtt_client = None,
        api_consume: bool = True
    ):
        self.logger = logging.getLogger(__name__)
        self._rpa_task_queue = rpa_task_queue
        self._task_counter = 0
        self._process_delay = process_delay
        self._callback_url = callback_url
        self._mqtt_client = mqtt_client
        self._api_consume = api_consume

        # 延迟队列：存储待延迟处理的API消息
        self._delayed_messages: List[APIMessage] = []
        self._delayed_lock = threading.Lock()
        self._is_running = True

        # 延迟处理线程
        self._process_thread: Optional[threading.Thread] = None

    def _generate_task_id(self) -> str:
        """生成唯一的任务ID"""
        self._task_counter += 1
        return f"task_{int(time.time() * 1000)}_{self._task_counter}"

    def start(self):
        """启动延迟处理线程"""
        if self._process_thread is None or not self._process_thread.is_alive():
            self._is_running = True
            self._process_thread = threading.Thread(target=self._process_loop, daemon=True)
            self._process_thread.start()
            self.logger.info("API消息延迟处理线程已启动")

    def stop(self):
        """停止延迟处理线程"""
        self._is_running = False
        if self._process_thread:
            self._process_thread.join(timeout=5)
            self.logger.info("API消息延迟处理线程已停止")

    def _process_loop(self):
        """延迟处理循环"""
        while self._is_running:
            try:
                self._process_delayed_messages()
                time.sleep(0.5)
            except Exception as e:
                self.logger.error(f"延迟处理循环出错: {e}")
                time.sleep(1)

    def _process_delayed_messages(self):
        """处理延迟队列中已到期的消息"""
        current_time = time.time()
        messages_to_process = []

        with self._delayed_lock:
            remaining_delayed = []
            for delayed_msg in self._delayed_messages:
                if current_time - delayed_msg.insert_time >= self._process_delay:
                    messages_to_process.append(delayed_msg)
                else:
                    remaining_delayed.append(delayed_msg)
            self._delayed_messages = remaining_delayed

        # 处理到期的消息
        for api_msg in messages_to_process:
            try:
                self._execute_action(api_msg.action_type, api_msg.action_data, api_msg.task_id)
            except Exception as e:
                self.logger.error(f"处理延迟消息时出错: {e}")

    def _execute_action(self, action_type: str, action_data: dict, task_id: str):
        """执行RPA动作并推送MQ"""
        try:
            action = None

            if action_type == "send_text":
                action = SendTextMessageAction(
                    content=action_data.get("message"),
                    target=action_data.get("recipient_name"),
                    at_user_name=action_data.get("at_user_name"),
                )
            elif action_type == "send_file":
                action = SendFileAction(
                    file_path=action_data.get("file_path"),
                    target=action_data.get("recipient_name"),
                    is_chatroom=False,
                )
            elif action_type == "recall_message":
                action = RecallMessageAction(
                    contact_name=action_data.get("contact_name"),
                    message_text=action_data.get("message_text", ""),
                    keyword=action_data.get("keyword", ""),
                    recall_latest=action_data.get("recall_latest", False),
                    similarity=action_data.get("similarity", 0.6),
                )

            if action:
                # 放入RPA任务队列
                self._rpa_task_queue.put(action)
                self.logger.info(f"API任务已执行: {task_id}, 类型: {action_type}")

                # 推送到MQTT（如果配置了MQTT客户端）
                if self._mqtt_client:
                    self._publish_to_mqtt(action_type, action_data, task_id)

                # 回调通知（如果配置了回调地址）
                if self._callback_url:
                    self._send_callback(action_type, action_data, task_id, "completed")

        except Exception as e:
            self.logger.error(f"执行动作失败: {e}")
            if self._callback_url:
                self._send_callback(action_type, action_data, task_id, "failed", str(e))

    def _publish_to_mqtt(self, action_type: str, action_data: dict, task_id: str):
        """发布消息到MQTT"""
        try:
            if self._mqtt_client:
                payload = {
                    "action_type": action_type,
                    "action_data": action_data,
                    "task_id": task_id,
                    "timestamp": time.time(),
                }
                # 发布到指定的MQTT主题
                topic = f"msg/api/{action_type}"
                self._mqtt_client.publish(topic, payload)
                self.logger.info(f"消息已发布到MQTT: {topic}, task_id: {task_id}")
        except Exception as e:
            self.logger.error(f"发布MQTT消息失败: {e}")

    def _send_callback(self, action_type: str, action_data: dict, task_id: str, status: str, error: str = ""):
        """发送回调通知"""
        try:
            if not self._callback_url:
                return

            callback_data = {
                "action_type": action_type,
                "action_data": action_data,
                "task_id": task_id,
                "status": status,
                "timestamp": time.time(),
            }
            if error:
                callback_data["error"] = error

            # 异步发送回调
            asyncio.create_task(self._async_send_callback(callback_data))
        except Exception as e:
            self.logger.error(f"发送回调通知失败: {e}")

    async def _async_send_callback(self, callback_data: dict):
        """异步发送回调请求"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self._callback_url,
                    json=callback_data,
                    headers={"Content-Type": "application/json"}
                )
                if response.status_code == 200:
                    self.logger.info(f"回调通知发送成功: {callback_data['task_id']}")
                else:
                    self.logger.warning(f"回调通知返回错误: {response.status_code}")
        except Exception as e:
            self.logger.error(f"回调请求失败: {e}")

    def _add_to_delayed_queue(self, action_type: str, action_data: dict, task_id: str):
        """将消息加入延迟队列"""
        with self._delayed_lock:
            self._delayed_messages.append(
                APIMessage(action_type, action_data, time.time(), task_id)
            )
        self.logger.info(f"API任务已加入延迟队列: {task_id}, 类型: {action_type}, 延迟{self._process_delay}秒处理")

    def send_text_message(self, request: SendTextRequest) -> APIResponse:
        """
        发送文本消息。

        Args:
            request: 发送文本消息请求

        Returns:
            APIResponse: 操作结果
        """
        try:
            task_id = self._generate_task_id()
            action_data = {
                "recipient_name": request.recipient_name,
                "message": request.message,
                "at_user_name": request.at_user_name,
            }

            # 立即回调通知（任务已接收）
            if self._callback_url:
                self._send_callback("send_text", action_data, task_id, "received")

            if self._api_consume and self._process_delay > 0:
                # 加入延迟队列
                self._add_to_delayed_queue("send_text", action_data, task_id)
            else:
                # 立即执行
                self._execute_action("send_text", action_data, task_id)

            self.logger.info(f"发送文本消息任务已提交: {task_id}, 接收者: {request.recipient_name}")

            return APIResponse(
                success=True,
                message=f"消息{'已提交到延迟队列' if self._api_consume and self._process_delay > 0 else '已提交'}，等待发送",
                task_id=task_id,
                data={
                    "recipient_name": request.recipient_name,
                    "message_length": len(request.message),
                }
            )

        except Exception as e:
            self.logger.error(f"发送文本消息失败: {str(e)}")
            return APIResponse(
                success=False,
                message=f"发送失败: {str(e)}",
                task_id=None
            )

    def send_file_message(self, request: SendFileRequest) -> APIResponse:
        """
        发送文件消息。

        Args:
            request: 发送文件请求

        Returns:
            APIResponse: 操作结果
        """
        try:
            task_id = self._generate_task_id()
            action_data = {
                "recipient_name": request.recipient_name,
                "file_path": request.file_path,
            }

            # 立即回调通知（任务已接收）
            if self._callback_url:
                self._send_callback("send_file", action_data, task_id, "received")

            if self._api_consume and self._process_delay > 0:
                # 加入延迟队列
                self._add_to_delayed_queue("send_file", action_data, task_id)
            else:
                # 立即执行
                self._execute_action("send_file", action_data, task_id)

            self.logger.info(f"发送文件任务已提交: {task_id}, 接收者: {request.recipient_name}")

            return APIResponse(
                success=True,
                message=f"文件发送任务{'已提交到延迟队列' if self._api_consume and self._process_delay > 0 else '已提交'}",
                task_id=task_id,
                data={
                    "recipient_name": request.recipient_name,
                    "file_path": request.file_path,
                }
            )

        except Exception as e:
            self.logger.error(f"发送文件失败: {str(e)}")
            return APIResponse(
                success=False,
                message=f"发送失败: {str(e)}",
                task_id=None
            )

    def recall_message(self, request: RecallMessageRequest) -> APIResponse:
        """
        撤回消息。

        Args:
            request: 撤回消息请求

        Returns:
            APIResponse: 操作结果
        """
        try:
            # 参数验证
            if not request.message_text and not request.keyword and not request.recall_latest:
                return APIResponse(
                    success=False,
                    message="请提供 message_text、keyword 或设置 recall_latest=True",
                    task_id=None
                )

            task_id = self._generate_task_id()
            action_data = {
                "contact_name": request.contact_name,
                "message_text": request.message_text or "",
                "keyword": request.keyword or "",
                "recall_latest": request.recall_latest,
                "similarity": request.similarity,
            }

            # 立即回调通知（任务已接收）
            if self._callback_url:
                self._send_callback("recall_message", action_data, task_id, "received")

            # 撤回消息不需要延迟处理，直接执行
            # 撤回是紧急操作，需要立即执行
            self._execute_action("recall_message", action_data, task_id)

            self.logger.info(f"撤回消息任务已提交: {task_id}, 联系人: {request.contact_name}")

            return APIResponse(
                success=True,
                message="撤回任务已提交",
                task_id=task_id,
                data={
                    "contact_name": request.contact_name,
                    "recall_type": "latest" if request.recall_latest else "text" if request.message_text else "keyword",
                }
            )

        except Exception as e:
            self.logger.error(f"撤回消息失败: {str(e)}")
            return APIResponse(
                success=False,
                message=f"撤回失败: {str(e)}",
                task_id=None
            )

    def get_queue_status(self) -> dict:
        """获取队列状态"""
        with self._delayed_lock:
            delayed_size = len(self._delayed_messages)
        return {
            "queue_size": self._rpa_task_queue.qsize(),
            "delayed_queue_size": delayed_size,
            "task_counter": self._task_counter,
            "process_delay": self._process_delay,
            "api_consume": self._api_consume,
            "mqtt_enabled": self._mqtt_client is not None,
            "callback_enabled": bool(self._callback_url),
        }


def create_api_service(
    rpa_task_queue: Queue,
    api_config: dict = None,
    mqtt_client = None
) -> tuple:
    """
    创建 API 服务。

    Args:
        rpa_task_queue: RPA 任务队列
        api_config: API配置字典
        mqtt_client: MQTT客户端实例

    Returns:
        tuple: (app, task_queue_manager)
    """
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError:
        # 如果没有 fastapi，返回 None
        return None, None

    api_config = api_config or {}

    app = FastAPI(
        title="Omni-Bot RPA API",
        description="微信 RPA 自动化任务接口，支持MQTT队列和延迟处理",
        version="1.1.0",
    )

    # 添加 CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 创建任务队列管理器
    task_manager = RPATaskQueue(
        rpa_task_queue=rpa_task_queue,
        process_delay=api_config.get("process_delay", 30),
        callback_url=api_config.get("callback_url", ""),
        mqtt_client=mqtt_client,
        api_consume=api_config.get("api_consume", True)
    )

    # 启动延迟处理线程
    task_manager.start()

    @app.get("/")
    async def root():
        """根路径"""
        return {
            "service": "Omni-Bot RPA API",
            "version": "1.1.0",
            "status": "running"
        }

    @app.get("/health")
    async def health():
        """健康检查"""
        return {"status": "healthy"}

    @app.get("/status")
    async def status():
        """队列状态"""
        return task_manager.get_queue_status()

    @app.post("/api/v1/send/text", response_model=APIResponse)
    async def api_send_text(request: SendTextRequest):
        """
        发送文本消息接口

        请求示例:
        ```json
        {
            "recipient_name": "张三",
            "message": "你好，这是一条测试消息",
            "at_user_name": null
        }
        ```
        """
        return task_manager.send_text_message(request)

    @app.post("/api/v1/send/file", response_model=APIResponse)
    async def api_send_file(request: SendFileRequest):
        """
        发送文件接口

        请求示例:
        ```json
        {
            "recipient_name": "张三",
            "file_path": "C:/path/to/file.pdf"
        }
        ```
        """
        return task_manager.send_file_message(request)

    @app.post("/api/v1/recall/message", response_model=APIResponse)
    async def api_recall_message(request: RecallMessageRequest):
        """
        撤回消息接口

        请求示例（按内容撤回）:
        ```json
        {
            "contact_name": "张三",
            "message_text": "要撤回的消息内容",
            "similarity": 0.6
        }
        ```

        请求示例（按关键词撤回）:
        ```json
        {
            "contact_name": "张三",
            "keyword": "关键词"
        }
        ```

        请求示例（撤回最新消息）:
        ```json
        {
            "contact_name": "张三",
            "recall_latest": true
        }
        ```
        """
        return task_manager.recall_message(request)

    return app, task_manager
