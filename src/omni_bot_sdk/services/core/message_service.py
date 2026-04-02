"""
消息服务模块。
提供消息的存储、检索、分发等服务。
"""

import logging
import threading
import time
from queue import Empty, Queue
from typing import Callable, Dict, List, Optional, Tuple
from pathlib import Path
from omni_bot_sdk.services.core.database_service import DatabaseService


class DelayedMessage:
    """延迟消息封装类"""
    def __init__(
        self,
        message: Tuple[str, tuple],
        insert_time: float,
        server_id: str,
        message_db_path: Path,
        username: str
    ):
        self.message = message
        self.insert_time = insert_time
        self.server_id = server_id
        self.message_db_path = message_db_path
        self.username = username


class MessageService:
    # 延迟队列最大容量
    MAX_DELAY_QUEUE_SIZE = 1000
    # 延迟时间（秒）
    DELAY_SECONDS = 60

    def __init__(self, message_queue: Queue, db: DatabaseService):
        self.logger = logging.getLogger(__name__)
        self.message_queue = message_queue
        self.db = db
        self.is_running = False
        self.is_paused = False  # 新增：用于标记是否暂停
        self.thread: Optional[threading.Thread] = None
        self.seen_message_types = set()  # 用于记录见过的消息类型
        self.callback: Optional[Callable] = None
        # 延迟队列：存储待延迟处理的消息
        self._delayed_messages: List[DelayedMessage] = []
        self._delayed_lock = threading.Lock()

    def start(self):
        """启动监听器"""
        if self.is_running:
            self.logger.warning("监听器已经在运行中")
            return False

        self.is_running = True
        self.thread = threading.Thread(target=self._message_loop)
        self.thread.daemon = True
        self.thread.start()
        self.logger.info("监听器已启动")
        return True

    def stop(self):
        """停止监听器"""
        if not self.is_running:
            self.logger.warning("监听器未在运行")
            return False

        self.is_running = False
        if self.thread:
            self.thread.join()
        self.logger.info("监听器已停止")
        return True

    def set_callback(self, callback: Callable):
        """设置消息回调函数"""
        self.callback = callback

    def pause(self):
        """
        暂停消息获取
        """
        if not self.is_running or self.is_paused:
            self.logger.info("消息监听器已暂停或未运行，无需重复暂停。")
            return
        self.is_paused = True
        self.logger.info("消息监听器已暂停。")

    def resume(self):
        """
        恢复消息获取
        """
        if not self.is_running or not self.is_paused:
            self.logger.info("消息监听器未暂停或未运行，无需恢复。")
            return
        self.is_paused = False
        self.logger.info("消息监听器已恢复。")

    def _is_recall_message(self, message: Tuple[str, tuple]) -> bool:
        """
        检查消息是否为撤回消息。

        Args:
            message: 消息元组 (table_name, msg_data)

        Returns:
            bool: 如果是撤回消息返回True，否则返回False
        """
        try:
            table_name, msg_data = message
            if len(msg_data) < 6:
                return False

            # 消息类型字段在 msg_data[2]
            msg_type = msg_data[2] if len(msg_data) > 2 else None

            # 撤回消息的特征：
            # 1. 消息类型为文本(1)或系统消息(10000)，但内容为特定撤回关键词
            # 2. 消息内容包含撤回相关文字
            content = msg_data[5] if len(msg_data) > 5 else ""  # 消息内容字段
            if content:
                # 检查撤回关键词
                recall_keywords = ["撤回了一条消息", "recalled a message", "撤回了消息"]
                content_str = str(content)
                for keyword in recall_keywords:
                    if keyword in content_str:
                        return True

            # 也可能是特定消息类型
            # 微信撤回消息的类型通常是文本或系统消息
            if msg_type in (1, 10000) and content:
                content_str = str(content).lower()
                if "撤回" in content_str or "recall" in content_str:
                    return True

            return False
        except Exception as e:
            self.logger.error(f"检查撤回消息时出错: {e}")
            return False

    def _contains_at_target(self, content: str) -> bool:
        """
        检查消息内容是否应该被跳过（不加入队列）。
        
        逻辑说明：
        1. 如果包含 @chatroom -> 跳过 (返回 True)
        2. 如果包含独立的 @chat -> 放行 (返回 False)
        3. 如果包含独立的 @let -> 放行 (返回 False)
        4. 其他所有情况 (不包含 @chat 且 不包含 @let) -> 跳过 (返回 True)

        Args:
            content: 消息内容

        Returns:
            bool: True = 跳过 (不放队列), False = 放行 (放队列)
        """
        import re

        if not content:
            return True  # 空内容直接跳过

        content_lower = content.lower()

        # 第一步：优先检查 @chatroom
        # 如果包含 @chatroom，无论是否看起来像 @chat，都直接跳过
        # 使用正则确保是独立单词，避免匹配到类似 mychatroom 的情况，视具体需求而定
        # 这里假设 @chatroom 也是以独立单词形式出现，如果只要 substring 存在即可，可去掉正则直接用 'in'
        if re.search(r'(?<![\w])@chatroom(?![\w])', content, re.IGNORECASE):
            return True  # 跳过

        # 第二步：检查是否包含独立的 @chat
        has_chat = bool(re.search(r'(?<![\w])@chat(?![\w])', content, re.IGNORECASE))
        
        # 第三步：检查是否包含独立的 @let
        has_let = bool(re.search(r'(?<![\w])@let(?![\w])', content, re.IGNORECASE))

        # 第四步：决策
        # 只有当包含 @chat 或者 @let 时，才放行 (返回 False)
        # 否则 (既没有 @chat 也没有 @let)，跳过 (返回 True)
        if has_chat or has_let:
            return False  # 放行，加入队列
        else:
            return True   # 跳过，不加入队列

    def _process_delayed_messages(self):
        """处理延迟队列中已到期的消息"""
        current_time = time.time()
        messages_to_process = []

        with self._delayed_lock:
            remaining_delayed = []
            for delayed_msg in self._delayed_messages:
                if current_time - delayed_msg.insert_time >= self.DELAY_SECONDS:
                    messages_to_process.append(delayed_msg)
                else:
                    remaining_delayed.append(delayed_msg)

            # 只保留未到期的消息
            self._delayed_messages = remaining_delayed

        # 处理到期的消息
        for delayed_msg in messages_to_process:
            try:
                msg = delayed_msg.message
                table_name, msg_data = msg
                msg_type = msg_data[2] if len(msg_data) > 2 else "unknown"
                # 延迟到期后，重新查询消息当前状态
                self.logger.info(
                    f"延迟消息处理，来自于{Path(msg_data[-1]).name} : {table_name}, 消息类型: {msg_type}"
                )
                self.message_queue.put(msg)

                if self.callback:
                    self.callback([msg])
            except Exception as e:
                self.logger.error(f"处理延迟消息时出错: {e}")

    def _message_loop(self):
        """监听循环"""
        while self.is_running:
            if self.is_paused:
                time.sleep(1)
                continue

            try:
                # 1. 先处理延迟队列中已到期的消息
                self._process_delayed_messages()

                # 2. 检测新消息并加入延迟队列
                new_messages = self.db.check_new_messages()
                if new_messages:
                    with self._delayed_lock:
                        for msg in new_messages:
                            table_name, msg_data = msg
                            msg_type = msg_data[2] if len(msg_data) > 2 else "unknown"

                            # 记录新的消息类型
                            if msg_type not in self.seen_message_types:
                                self.seen_message_types.add(msg_type)
                                self.logger.info(f"发现新消息类型: {msg_type}")

                            print(f"msg_data: {msg_data}")
                            # 检查消息内容是否包含 @chat/@let/@chatroom，这些需要加入队列
                            # content = msg_data[12] if len(msg_data) > 12 else ""
                            # if content and self._contains_at_target(str(content)):
                            #     continue

                            # 只处理 msg_type = 1 的消息，其他类型不加入延迟队列
                            if msg_type != 1:
                                self.logger.info(
                                    f"跳过非文本消息: {table_name}, 类型: {msg_type}"
                                )
                                continue

                            # 检查延迟队列容量
                            if len(self._delayed_messages) >= self.MAX_DELAY_QUEUE_SIZE:
                                self.logger.warning(
                                    f"延迟队列已满({self.MAX_DELAY_QUEUE_SIZE})，丢弃最旧的消息"
                                )
                                self._delayed_messages.pop(0)

                            # 提取必要参数用于延迟后重新查询
                            server_id = str(msg_data[1]) if len(msg_data) > 1 else ""
                            message_db_path = Path(msg_data[-1]) if msg_data else Path("")
                            # table_name 格式为 "Msg_xxxxx"，xxxxx 即为 username
                            username = table_name.replace("Msg_", "") if table_name.startswith("Msg_") else ""

                            # 加入延迟队列
                            self._delayed_messages.append(
                                DelayedMessage(
                                    msg, time.time(),
                                    server_id, message_db_path, username
                                )
                            )
                            self.logger.info(
                                f"新消息加入延迟队列，来自于{Path(msg_data[-1]).name} : {table_name}, "
                                f"消息类型: {msg_type}, server_id: {server_id}, 延迟{self.DELAY_SECONDS}秒处理"
                            )

                    self.logger.info(f"延迟队列大小: {len(self._delayed_messages)}")

                # 每次循环间隔
                time.sleep(0.1)  # 减少轮询间隔，提高检测灵敏度
            except Empty:
                # 队列为空，继续下一次循环
                time.sleep(1)
                continue
            except Exception as e:
                if self.is_running:  # 忽略超时异常
                    self.logger.error(f"处理消息时出错: {e}")
                    time.sleep(1)

    def get_status(self) -> dict:
        """获取监听器状态"""
        with self._delayed_lock:
            delayed_queue_size = len(self._delayed_messages)
        return {
            "is_running": self.is_running,
            "queue_size": self.message_queue.qsize(),
            "delayed_queue_size": delayed_queue_size
        }
