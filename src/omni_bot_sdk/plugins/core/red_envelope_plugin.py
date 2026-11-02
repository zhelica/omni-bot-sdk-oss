"""
群红包监听插件。
收到群红包后（经 message_service 延迟），触发 RPA 打开红包详情并记录领取明细。
"""

from typing import TYPE_CHECKING

from pydantic import BaseModel

from omni_bot_sdk.plugins.interface import (
    Plugin,
    PluginExcuteContext,
    PluginExcuteResponse,
)
from omni_bot_sdk.rpa.action_handlers import RecordRedEnvelopeAction
from omni_bot_sdk.weixin.message_classes import MessageType

if TYPE_CHECKING:
    from omni_bot_sdk.bot import Bot


class RedEnvelopePluginConfig(BaseModel):
    """群红包监听插件配置。"""

    enabled: bool = True
    priority: int = 1600
    # 仅处理群聊红包；私聊忽略
    group_only: bool = True
    # 领取明细回调，空则使用 rpa_api.callback_url
    callback_url: str = ""
    # 抓取成功后把领取明细发回群聊
    send_to_group: bool = True


class RedEnvelopePlugin(Plugin):
    """监听群红包并记录领取情况。"""

    priority = 1600
    name = "red-envelope-plugin"

    def __init__(self, bot: "Bot" = None):
        super().__init__(bot)
        self.priority = getattr(self.plugin_config, "priority", self.__class__.priority)

    def get_priority(self) -> int:
        return self.priority

    def _resolve_callback_url(self) -> str:
        url = (getattr(self.plugin_config, "callback_url", "") or "").strip()
        if url:
            return url
        return (self.bot.config.get("rpa_api", {}) or {}).get("callback_url", "") or ""

    async def handle_message(self, context: PluginExcuteContext) -> None:
        message = context.get_message()
        if message.local_type != MessageType.RedEnvelope:
            return

        self.logger.info(
            f"red-envelope-plugin 收到红包消息: "
            f"is_chatroom={message.is_chatroom}, "
            f"room={getattr(message.room, 'display_name', None)}, "
            f"server_id={message.server_id}"
        )

        group_only = getattr(self.plugin_config, "group_only", True)
        if group_only and not message.is_chatroom:
            self.logger.info("忽略私聊红包消息")
            return

        target = (
            message.room.display_name
            if message.room
            else (message.contact.display_name if message.contact else "")
        )
        if not target:
            self.logger.warning("红包消息缺少会话名称，跳过")
            return

        title = getattr(message, "title", "") or ""
        room_id = message.room.username if message.room else ""
        callback_url = self._resolve_callback_url()

        self.logger.info(
            f"检测到群红包，准备记录领取明细: room={target}, title={title}, "
            f"server_id={message.server_id}"
        )

        send_to_group = getattr(self.plugin_config, "send_to_group", True)
        action = RecordRedEnvelopeAction(
            target=target,
            is_chatroom=bool(message.is_chatroom),
            title=title,
            room_id=room_id,
            callback_url=callback_url,
            server_id=str(message.server_id or ""),
            send_to_group=bool(send_to_group),
        )
        context.add_response(
            PluginExcuteResponse(
                message=message,
                plugin_name=self.name,
                should_stop=False,
                actions=[action],
            )
        )

    def get_plugin_name(self) -> str:
        return self.name

    def get_plugin_description(self) -> str:
        return "监听群红包，领完后点「查看领取详情」记录并回发领取明细"

    @classmethod
    def get_plugin_config_schema(cls):
        return RedEnvelopePluginConfig
