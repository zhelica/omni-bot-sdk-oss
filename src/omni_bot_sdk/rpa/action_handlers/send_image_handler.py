import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pyautogui
from omni_bot_sdk.rpa.action_handlers.base_handler import (
    BaseActionHandler,
    RPAAction,
    RPAActionType,
)
from omni_bot_sdk.utils.helpers import read_temp_image


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
            if not read_temp_image(action.image_path):
                return False
            logger.info(f"图片已复制到剪贴板: {action.image_path}")
            time.sleep(self.controller.window_manager.action_delay)
            # 搜索选联系人只允许一次鼠标点击；不要再点输入框（第二次点击易触发资料卡等弹窗）
            logger.info("执行 Ctrl+V 粘贴图片")
            pyautogui.hotkey("ctrl", "v")
            time.sleep(1)

            # 直接回车发送
            logger.info("回车发送")
            pyautogui.press("enter")
            time.sleep(0.3)
            logger.info("图片发送成功")
            return True
        finally:
            self._cleanup()
