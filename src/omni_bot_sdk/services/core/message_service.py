"""
消息服务模块。
提供消息的存储、检索、分发等服务。
"""

import logging
import re
import threading
import time
from queue import Empty, Queue
from typing import Callable, Dict, List, Optional, Tuple
from pathlib import Path
import httpx
from omni_bot_sdk.services.core.database_service import DatabaseService
from omni_bot_sdk.weixin.parser.util.common import decompress


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
    MAX_DELAY_QUEUE_SIZE = 1000

    def __init__(self, message_queue: Queue, db: DatabaseService, auto_consume: bool = True, delay_seconds: int = 30, callback_url: str = ""):
        self.logger = logging.getLogger(__name__)
        self.message_queue = message_queue
        self.db = db
        self.is_running = False
        self.is_paused = False
        self.auto_consume = auto_consume
        self.DELAY_SECONDS = delay_seconds
        self.callback_url = callback_url
        self.thread: Optional[threading.Thread] = None
        self.seen_message_types = set()
        self.callback: Optional[Callable] = None
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

            self._delayed_messages = remaining_delayed

        for delayed_msg in messages_to_process:
            try:
                msg = delayed_msg.message
                table_name, msg_data = msg
                msg_type = msg_data[2] if len(msg_data) > 2 else "unknown"

                self.logger.info(
                    f"延迟消息处理，来自于{Path(msg_data[-1]).name} : {table_name}, 消息类型: {msg_type}"
                )

                # 放入消息队列
                self.message_queue.put(msg)

                # 调用回调
                if self.callback:
                    self.callback([msg])

                # 发送到回调URL
                if self.callback_url:
                    self._send_to_callback(delayed_msg, msg_data)
            except Exception as e:
                self.logger.error(f"处理延迟消息时出错: {e}")

    def _send_to_callback(self, delayed_msg: DelayedMessage, msg_data: tuple):
        """发送消息到回调URL"""
        try:
            # 从 msg_data 中提取解密后的内容
            content = self._extract_content(msg_data)

            callback_data = {
                "server_id": delayed_msg.server_id,
                "username": delayed_msg.username,
                "content": content
            }

            response = httpx.post(
                self.callback_url,
                json=callback_data,
                timeout=10
            )
            self.logger.info(f"消息已回调至 {self.callback_url}, 响应: {response.status_code}")
        except Exception as e:
            self.logger.error(f"发送回调失败: {e}")

    def _extract_content(self, msg_data: tuple) -> str:
        """从消息数据中提取解密后的文本内容"""
        for item in msg_data:
            if isinstance(item, str):
                text = re.sub(r'[\u2005\u2007\u2009\u3000\xa0]', ' ', item)
                if '@chat' in text or '@let' in text:
                    return text
            elif isinstance(item, bytes):
                try:
                    decoded = decompress(item)
                    if decoded:
                        decoded = re.sub(r'[\u2005\u2007\u2009\u3000\xa0]', ' ', decoded)
                        if '@chat' in decoded or '@let' in decoded:
                            return decoded
                except Exception:
                    pass
                try:
                    decoded = item.decode('utf-8')
                    decoded = re.sub(r'[\u2005\u2007\u2009\u3000\xa0]', ' ', decoded)
                    if '@chat' in decoded or '@let' in decoded:
                        return decoded
                except Exception:
                    pass
        return ""

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

                            # 只处理 msg_type = 1 的消息，其他类型不加入延迟队列
                            if msg_type != 1:
                                self.logger.info(
                                    f"跳过非文本消息: {table_name}, 类型: {msg_type}"
                                )
                                continue

                            # 提取必要参数
                            self.logger.info(f"msg_data: {msg_data}")
                            server_id = str(msg_data[1]) if len(msg_data) > 1 else ""
                            username = table_name.replace("Msg_", "") if table_name.startswith("Msg_") else ""
                            sender_id = msg_data[4] if len(msg_data) > 4 else ""
                            message_db_path = msg_data[17] if len(msg_data) > 17 else None
                            content = ""
                            sender_wxid = ""  # 发送者 wxid
                            sender_name = ""  # 原始发送者名称
                            has_at_keyword = False

                            # 遍历 msg_data，提取内容和发送者信息
                            for i, item in enumerate(msg_data):
                                if isinstance(item, str):
                                    text = re.sub(r'[\u2005\u2007\u2009\u3000\xa0]', ' ', item)
                                    # 解析发送者信息
                                    if not sender_name and ':' in item:
                                        first_line = item.split('\n')[0]
                                        sender_name = first_line.rstrip(':')
                                        if sender_name.startswith('wxid_') or sender_name.startswith('gh_'):
                                            sender_wxid = sender_name
                                    # 提取包含关键字的消息
                                    if '@chat' in text or '@let' in text:
                                        content = text
                                        # 去掉发送者前缀
                                        if sender_name:
                                            content = content.replace(f'{sender_name}:\n', '')
                                            content = content.replace(f'{sender_name}:', '')
                                        has_at_keyword = True
                                        self.logger.info(f"在 msg_data[{i}] 字符串中找到包含@的关键内容")
                                        break
                                elif isinstance(item, bytes):
                                    try:
                                        decoded = decompress(item) if 'decompress' in dir() else None
                                        if not decoded:
                                            decoded = item.decode('utf-8')
                                        if decoded:
                                            decoded = re.sub(r'[\u2005\u2007\u2009\u3000\xa0]', ' ', decoded)
                                            if '@chat' in decoded or '@let' in decoded:
                                                content = decoded
                                                # 去掉发送者前缀
                                                if sender_name:
                                                    content = content.replace(f'{sender_name}:\n', '')
                                                    content = content.replace(f'{sender_name}:', '')
                                                has_at_keyword = True
                                                self.logger.info(f"在 msg_data[{i}] 解密后找到包含@的关键内容")
                                                break
                                    except Exception:
                                        pass

                            # 如果没有找到包含@的消息，尝试从 msg_data[12] 提取纯文本内容
                            if not content and len(msg_data) > 12:
                                item_12 = msg_data[12]
                                if isinstance(item_12, str):
                                    # 去掉发送者前缀获取纯文本
                                    if sender_name:
                                        content = item_12.replace(f'{sender_name}:\n', '')
                                        content = content.replace(f'{sender_name}:', '')
                                    else:
                                        content = item_12

                            self.logger.info(f"content: {content}, sender_wxid: {sender_wxid}, sender_name: {sender_name}")

                            # 如果配置了回调URL，发送回调（所有消息都会回调，包括私聊和群聊）
                            if self.callback_url:
                                try:
                                    room_name = ""
                                    room_id = ""
                                    sender_name = ""  # 发送者昵称
                                    is_group_chat = False
                                    
                                    # 首先通过 get_room_by_md5 判断是否为群聊消息
                                    if username:
                                        room = self.db.get_room_by_md5(username)
                                        if room:
                                            # 群聊消息
                                            is_group_chat = True
                                            room_id = room.username
                                            room_name = room.nick_name or room.remark or username
                                            sender_name = sender_wxid  # 群聊时发送者是wxid
                                            self.logger.info(f"查询到群: room_id={username}, room_name={room_name}")
                                        else:
                                            # 可能是私聊，尝试通过 get_contact_by_username 查询
                                            self.logger.info(f"未通过md5找到群，尝试通过get_contact_by_username查询: username={username}")
                                            contact = self.db.get_contact_by_sender_id(msg_data[4], msg_data[17])
                                            if contact:
                                                sender_name = contact.display_name or contact.nick_name or sender_wxid or username
                                                self.logger.info(f"通过username查询到联系人: name={sender_name}, display_name={contact.display_name}, nick_name={contact.nick_name}")
                                            else:
                                                sender_name = sender_wxid or username
                                                self.logger.info(f"未通过username找到联系人，使用默认: sender_name={sender_name}")
                                            self.logger.info(f"私聊消息: username={username}, sender_wxid={sender_wxid}")

                                    # 根据消息类型确定 contact_name
                                    if is_group_chat:
                                        # 群聊消息：contact_name 为 room_id
                                        contact_name = room_id
                                    else:
                                        # 私聊消息：contact_name 为 sender_wxid 或 username
                                        contact_name = sender_wxid or username

                                    callback_data = {
                                        "server_id": server_id,
                                        "content": content,
                                        "msg_type": msg_type,
                                        "contact_name": contact_name,
                                        "room_name": room_name,
                                        "room_id": room_id,
                                        "sender_wxid": sender_wxid,
                                        "sender_name": sender_name,
                                        "is_group_chat": is_group_chat
                                    }
                                    self.logger.info(f"回调数据: {callback_data}")
                                    response = httpx.post(
                                        self.callback_url,
                                        json=callback_data,
                                        timeout=10
                                    )
                                    self.logger.info(
                                        f"消息已回调至 {self.callback_url}, 响应: {response.status_code}"
                                    )
                                except Exception as e:
                                    self.logger.error(f"发送回调失败: {e}")

                            # 检查是否包含 @chat/@let 关键字
                            if not has_at_keyword:
                                self.logger.info(
                                    f"跳过不包含@chat或@let的消息: {table_name}"
                                )
                                continue

                            # 检查是否启用自动消费（本地队列处理）
                            if not self.auto_consume:
                                self.logger.info(
                                    f"自动消费已关闭，跳过消息: {table_name}"
                                )
                                continue

                            # 检查延迟队列容量
                            if len(self._delayed_messages) >= self.MAX_DELAY_QUEUE_SIZE:
                                self.logger.warning(
                                    f"延迟队列已满({self.MAX_DELAY_QUEUE_SIZE})，丢弃最旧的消息"
                                )
                                self._delayed_messages.pop(0)

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
            "is_paused": self.is_paused,
            "auto_consume": self.auto_consume,
            "queue_size": self.message_queue.qsize(),
            "delayed_queue_size": delayed_queue_size
        }

    def set_auto_consume(self, enabled: bool):
        """设置是否启用自动消费"""
        self.auto_consume = enabled
        self.logger.info(f"自动消费已{'启用' if enabled else '关闭'}")
