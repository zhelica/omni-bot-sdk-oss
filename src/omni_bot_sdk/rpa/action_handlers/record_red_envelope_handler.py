"""
记录红包领取明细 Action Handler。
延迟后切换到群聊，点击红包卡片 →「查看领取详情」→ OCR 解析领取人与金额 → 发回群聊。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from omni_bot_sdk.rpa.action_handlers import RPAAction, RPAActionType
from omni_bot_sdk.rpa.action_handlers.base_handler import BaseActionHandler
from omni_bot_sdk.rpa.red_envelope_recorder import RedEnvelopeRecorder


@dataclass
class RecordRedEnvelopeAction(RPAAction):
    """记录红包领取明细动作。"""

    target: str = ""
    is_chatroom: bool = True
    title: str = ""
    room_id: str = ""
    callback_url: str = ""
    server_id: str = ""
    claims: List[Dict[str, Any]] = field(default_factory=list)
    # 是否将领取明细发回群聊
    send_to_group: bool = True

    def __post_init__(self):
        self.action_type = RPAActionType.RECORD_RED_ENVELOPE
        self.is_send_message = False

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update(
            {
                "target": self.target,
                "is_chatroom": self.is_chatroom,
                "title": self.title,
                "room_id": self.room_id,
                "callback_url": self.callback_url,
                "server_id": self.server_id,
                "claims": self.claims,
                "send_to_group": self.send_to_group,
            }
        )
        return base


class RecordRedEnvelopeHandler(BaseActionHandler):
    """红包领取记录处理器。"""

    def __init__(self, controller):
        super().__init__(controller)
        self._recorder = None

    def _get_recorder(self) -> RedEnvelopeRecorder:
        if self._recorder is None:
            self._recorder = RedEnvelopeRecorder(self.controller.window_manager)
        return self._recorder

    def _send_claims_to_group(
        self, target: str, claims: List[Dict[str, Any]], title: str
    ) -> bool:
        content = RedEnvelopeRecorder.format_claims_message(claims, title=title)
        self.logger.info(f"向群发送红包领取记录:\n{content}")
        # 详情已关闭，仍应在目标会话中；再切一次保证输入框可用
        if not self.window_manager.switch_session(target):
            self.logger.error(f"发送领取记录前切换会话失败: {target}")
            return False
        return self.controller.message_sender.send_message(
            content, clear_input_box=True
        )

    def execute(self, action: RecordRedEnvelopeAction) -> bool:
        try:
            if not action.target:
                self.logger.error("RecordRedEnvelopeAction 缺少 target")
                return False

            recorder = self._get_recorder()
            result = recorder.record(
                contact_name=action.target,
                title=action.title,
                callback_url=action.callback_url,
                room_id=action.room_id,
                extra={"server_id": action.server_id} if action.server_id else None,
            )
            action.claims = result.get("claims") or []

            if not result.get("success"):
                self.logger.warning(result.get("message", "红包领取记录失败"))
                return False

            self.logger.info(result.get("message", "红包领取记录成功"))

            if action.send_to_group and action.is_chatroom:
                if not self._send_claims_to_group(
                    action.target, action.claims, action.title
                ):
                    self.logger.warning("红包领取记录已抓取，但发群失败")
                    # 抓取成功仍视为整体成功
            return True
        except Exception as e:
            self.logger.error(f"执行红包领取记录失败: {e}", exc_info=True)
            return False
        finally:
            self._cleanup()
