"""
消息撤回 Action Handler。
通过OCR识别和右键菜单实现消息撤回功能。
"""

import logging
from dataclasses import dataclass
from typing import Any

from omni_bot_sdk.rpa.action_handlers import RPAAction, RPAActionType
from omni_bot_sdk.rpa.action_handlers.base_handler import BaseActionHandler
from omni_bot_sdk.rpa.message_recall import MessageRecallController


@dataclass
class RecallMessageAction(RPAAction):
    """
    撤回消息动作。
    """

    contact_name: str = ""  # 联系人名称
    message_text: str = ""  # 要撤回的消息内容
    keyword: str = ""  # 关键词（当message_text为空时使用）
    recall_latest: bool = False  # 是否撤回最新消息
    similarity: float = 0.6  # 相似度阈值

    def __post_init__(self):
        self.action_type = RPAActionType.RECALL_MESSAGE
        self.is_send_message = False  # 撤回消息不受速率限制

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "contact_name": self.contact_name,
            "message_text": self.message_text,
            "keyword": self.keyword,
            "recall_latest": self.recall_latest,
            "similarity": self.similarity,
        })
        return base


class RecallMessageHandler(BaseActionHandler):
    """
    消息撤回处理器。
    流程：
    1. 搜索并切换到目标联系人
    2. 在聊天区域通过OCR识别消息
    3. 右键点击目标消息
    4. 在菜单中通过OCR识别并点击"撤回"
    """

    def __init__(self, controller):
        super().__init__(controller)
        self.recall_controller = None

    def _get_recall_controller(self) -> MessageRecallController:
        """获取撤回控制器实例（延迟初始化）"""
        if self.recall_controller is None:
            self.recall_controller = MessageRecallController(self.controller.window_manager)
        return self.recall_controller

    def execute(self, action: RecallMessageAction) -> bool:
        """
        执行消息撤回操作。

        Args:
            action: RecallMessageAction实例

        Returns:
            bool: 撤回是否成功
        """
        try:
            controller = self._get_recall_controller()

            # 确定撤回方式
            if action.recall_latest:
                self.logger.info(f"撤回 {action.contact_name} 的最新消息")
                return controller.recall_latest_message(
                    contact_name=action.contact_name,
                    max_retries=2,
                )

            elif action.message_text:
                self.logger.info(f"撤回 {action.contact_name} 中包含 '{action.message_text}' 的消息")
                return controller.recall_by_text(
                    contact_name=action.contact_name,
                    message_text=action.message_text,
                    similarity_threshold=action.similarity,
                    max_retries=2,
                )

            elif action.keyword:
                self.logger.info(f"撤回 {action.contact_name} 中包含关键词 '{action.keyword}' 的消息")
                return controller.recall_by_keyword(
                    contact_name=action.contact_name,
                    keyword=action.keyword,
                    max_retries=2,
                )

            else:
                self.logger.error("未提供 message_text、keyword 或 recall_latest 参数")
                return False

        except Exception as e:
            self.logger.error(f"执行消息撤回失败: {str(e)}", exc_info=True)
            return False
