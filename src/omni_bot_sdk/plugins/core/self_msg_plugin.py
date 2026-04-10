from typing import TYPE_CHECKING
from pathlib import Path
from pydantic import BaseModel

from omni_bot_sdk.plugins.interface import Plugin, PluginExcuteContext

if TYPE_CHECKING:
    from omni_bot_sdk.bot import Bot


class SelfMsgPluginConfig(BaseModel):
    """
    自我消息插件配置
    enabled: 是否启用该插件
    priority: 插件优先级，数值越大优先级越高
    """

    enabled: bool = False
    priority: int = 1000


class SelfMsgPlugin(Plugin):
    """
    自我消息处理插件实现类

    继承自Plugin基类，用于处理用户自己发送的消息。
    作为消息处理链中的第一个插件，用于拦截用户自己发送的消息，防止这些消息进入后续处理流程。

    属性：
        priority (int): 插件优先级，设置为1000确保最先执行
        name (str): 插件名称标识符
    """

    priority = 1000
    name = "self-msg-plugin"

    def __init__(self, bot: "Bot" = None):
        super().__init__(bot)
        self.priority = getattr(self.plugin_config, "priority", self.__class__.priority)

    def get_priority(self) -> int:
        return self.priority

    def check_message_recalled(
        self, server_id: int, message_db_path: Path, username: str
    ) -> bool:
        """
        通过内置 get_message_by_server_id 方法查询消息，判断消息是否被撤回

        Args:
            server_id: 消息的服务器ID
            message_db_path: 消息所在数据库的路径
            username: 会话用户名 (talker)

        Returns:
            bool: 如果消息被撤回返回 True，否则返回 False
        """
        try:
            message_data = self.bot.db.get_message_by_server_id(
                str(server_id), message_db_path, username
            )
            if message_data is None:
                self.logger.info(f"未找到消息: server_id={server_id}")
                return False

            local_type = message_data[2] if len(message_data) > 2 else 0

            if local_type == 10000:
                self.logger.info(f"检测到消息被撤回: server_id={server_id}, local_type={local_type}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"查询消息撤回状态失败: {e}")
            return False

    async def handle_message(self, plusginExcuteContext: PluginExcuteContext) -> None:
        message = plusginExcuteContext.get_message()
        username = message.room.username if message.room else None

        if message.is_self:
            self.logger.info("检测到是自己的消息，直接拦截，不再让后续的处理")
            plusginExcuteContext.should_stop = True
            return

        if username and message.server_id and message.message_db_path:
            is_recalled = self.check_message_recalled(
                message.server_id,
                Path(message.message_db_path),
                username
            )
            if is_recalled:
                self.logger.info("检测到是撤回的消息，直接拦截，不再让后续的处理")
                plusginExcuteContext.should_stop = True
                return

        self.logger.info("消息通过校验")
        plusginExcuteContext.should_stop = False

    def get_plugin_name(self) -> str:
        return self.name

    def get_plugin_description(self) -> str:
        return "这是一个用于处理用户自己发送消息的插件，用于拦截自己发送的消息"

    @classmethod
    def get_plugin_config_schema(cls):
        """
        返回插件配置的pydantic schema类。
        """
        return SelfMsgPluginConfig
