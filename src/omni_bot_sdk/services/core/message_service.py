"""
消息服务模块。
提供消息的存储、检索、分发等服务。
"""

import logging
import threading
import time
from queue import Empty, Queue
from typing import Callable, Optional
from pathlib import Path
from omni_bot_sdk.services.core.database_service import DatabaseService


class MessageService:
    def __init__(self, message_queue: Queue, db: DatabaseService):
        self.logger = logging.getLogger(__name__)
        self.message_queue = message_queue
        self.db = db
        self.is_running = False
        self.is_paused = False  # 新增：用于标记是否暂停
        self.thread: Optional[threading.Thread] = None
        self.seen_message_types = set()  # 用于记录见过的消息类型
        self.callback: Optional[Callable] = None

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

    def _message_loop(self):
        """监听循环"""
        while self.is_running:
            if self.is_paused:
                time.sleep(1)
                continue
            try:
                # 添加调试信息：记录每次数据库查询
                # self.logger.info("开始查询新消息...")
                message = self.db.check_new_messages()
                if message:
                    for msg in message:
                        # 详细记录消息信息，包括消息类型
                        table_name, msg_data = msg
                        msg_type = msg_data[2] if len(msg_data) > 2 else "unknown"
                        
                        # 记录新的消息类型
                        if msg_type not in self.seen_message_types:
                            self.seen_message_types.add(msg_type)
                            self.logger.info(f"发现新消息类型: {msg_type}")
                        
                        self.logger.info(
                            f"新消息插入队列，来自于{Path(msg[1][-1]).name} : {msg[0]}, 消息类型: {msg_type}"
                        )
                        self.message_queue.put(msg)
                    self.logger.info(f"消息队列大小: {self.message_queue.qsize()}")
                    # 保存消息到数据库
                    if self.callback:
                        self.callback(message)
                # else:
                    # 添加调试信息：当没有检测到新消息时也记录
                    # self.logger.info("本次轮询未检测到新消息")
                time.sleep(0.1)  # 减少轮询间隔，提高检测灵敏度
            except Empty:
                # 队列为空，继续下一次循环
                time.sleep(1)  #
                continue
            except Exception as e:
                if self.is_running:  # 忽略超时异常
                    self.logger.error(f"处理消息时出错: {e}")
                    time.sleep(1)  #

    def get_status(self) -> dict:
        """获取监听器状态"""
        return {"is_running": self.is_running, "queue_size": self.message_queue.qsize()}
