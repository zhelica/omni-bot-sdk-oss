import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pyautogui
from omni_bot_sdk.rpa.action_handlers.base_handler import (
    BaseActionHandler,
    RPAAction,
    RPAActionType,
)
from omni_bot_sdk.utils.helpers import copy_file_to_clipboard


@dataclass
class SendImageAction(RPAAction):
    """
    发送图片操作。
    Attributes:
        image_path (str): 图片文件路径。
        target (str): 目标用户或群聊的标识。
        is_chatroom (bool): 是否为群聊。
    """

    image_path: Optional[str] = None
    target: Optional[str] = None
    is_chatroom: bool = False

    def __post_init__(self):
        self.action_type = RPAActionType.SEND_IMAGE
        self.is_send_message = True


class SendImageHandler(BaseActionHandler):
    """
    发送图片操作的处理器。
    """

    def execute(self, action: SendImageAction) -> bool:
        """
        执行发送图片操作。
        Args:
            action (SendImageAction): 操作对象。
        Returns:
            bool: 操作是否成功。
        """
        import logging
        logger = logging.getLogger(__name__)
        try:
            if not self.window_manager.switch_session(action.target):
                return False
            if not copy_file_to_clipboard(action.image_path):
                return False
            logger.info(f"图片已复制到剪贴板: {action.image_path}")
            time.sleep(self.controller.window_manager.action_delay)

            # 先激活输入框获取焦点
            if not self.window_manager.activate_input_box():
                logger.error("激活输入框失败")
                return False
            time.sleep(self.controller.window_manager.action_delay)

            # 粘贴图片
            logger.info("执行 Ctrl+V 粘贴图片")
            pyautogui.hotkey("ctrl", "v")
            time.sleep(1)

            # 点击发送按钮
            logger.info("点击发送按钮")
            if self.ui_helper.click_send_button():
                logger.info("图片发送成功")
                return True
            logger.error("点击发送按钮失败")
            return False
        finally:
            self._cleanup()
