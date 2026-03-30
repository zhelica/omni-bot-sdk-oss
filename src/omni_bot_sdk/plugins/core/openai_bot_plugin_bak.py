import time
from typing import Optional

import openai
from pydantic import BaseModel
from omni_bot_sdk.plugins.interface import (
    Bot,
    Plugin,
    PluginExcuteContext,
    PluginExcuteResponse,
    MessageType,
    SendTextMessageAction,
)


class OpenAIBotPluginConfig(BaseModel):
    """
    OpenAI Bot 插件配置
    enabled: 是否启用该插件
    openai_api_key: OpenAI API密钥
    openai_base_url: OpenAI API基础URL
    openai_model: OpenAI模型名称
    priority: 插件优先级，数值越大优先级越高
    prompt: 系统提示词，支持 {{chat_history}}、{{time_now}}、{{self_nickname}}、{{room_nickname}}、{{contact_nickname}} 变量占位符
    """

    enabled: bool = True
    openai_api_key: str = "sk-20bd5387ed5f470a870cbdf01516913e"
    openai_base_url: str = "https://api.deepseek.com/v1/"
    openai_model: str = "deepseek-chat"
    priority: int = 100
    prompt: str = (
        "你是一个聊天机器人，请根据用户的问题给出回答。历史对话：{{chat_history}} 当前时间：{{time_now}} "
        "你的昵称：{{self_nickname}} 群昵称：{{room_nickname}} 消息来自于：{{contact_nickname}}"
    )


class OpenAIBotPlugin(Plugin):
    """
    OpenAI 聊天机器人插件实现类
    """

    priority = 100
    name = "openai-bot-plugin"

    def __init__(self, bot: "Bot"):
        super().__init__(bot)
        self.api_key = self.plugin_config.openai_api_key
        self.base_url = self.plugin_config.openai_base_url
        self.model = self.plugin_config.openai_model
        self.enabled = self.plugin_config.enabled
        self.priority = getattr(self.plugin_config, "priority", self.__class__.priority)
        self.user = bot.user_info
        self.prompt = self.plugin_config.prompt
        openai.api_key = self.api_key
        openai.base_url = self.base_url

    def get_ai_response(self, msg, chat_history) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            if msg.local_type == MessageType.Quote:
                content = msg.content
            else:
                content = (
                    msg.parsed_content.replace(f"@{self.user.nickname}", "")
                    .replace("\u2005", "")
                    .strip()
                )
            # 构造 OpenAI 聊天消息，历史消息作为知识背景，拼接到 prompt 占位符
            messages = []
            # 支持多变量替换
            time_now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            system_prompt = self.prompt
            system_prompt = system_prompt.replace(
                "{{chat_history}}", chat_history or ""
            )
            system_prompt = system_prompt.replace("{{time_now}}", time_now)
            # 下面变量由用户手动创建和传递，这里默认字符串
            system_prompt = system_prompt.replace(
                "{{self_nickname}}", self.user.nickname
            )
            system_prompt = system_prompt.replace(
                "{{room_nickname}}", msg.room.display_name if msg.room else ""
            )
            system_prompt = system_prompt.replace(
                "{{contact_nickname}}", msg.contact.display_name if msg.contact else ""
            )
            messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": content})
            response = openai.chat.completions.create(
                model=self.model,
                messages=messages,
                user=msg.room.username if msg.is_chatroom else msg.contact.username,
            )
            # OpenAI 返回格式
            answer = response.choices[0].message.content.strip()
            return answer
        except Exception as e:
            self.logger.error(f"获取AI响应时出错: {e}")
            return None

    def get_priority(self) -> int:
        return self.priority

    async def handle_message(self, plusginExcuteContext: PluginExcuteContext) -> None:
        """
        处理接收到的消息
        文本消息，引用消息处理，其他都先不处理
        文本消息要判断是不是 at 我，或者是不是引用了我
        前面的上下文插件会在上下文中添加 not_for_bot 字段，如果为True，则不进行AI回复
        """
        if not self.enabled:
            return
        message = plusginExcuteContext.get_message()
        if (
            message.local_type != MessageType.Text
            and message.local_type != MessageType.Quote
        ):
            return
        context = plusginExcuteContext.get_context()
        not_for_bot = context.get("not_for_bot", False)
        if (
            not_for_bot
        ):  # 用户可能没有前置判断流程，这里需要采用一般逻辑，也就是私聊消息全部回复，群聊消息除了@和引用不回复，这是典型的机器人特征
            return
        chat_history = context.get("chat_history", "")
        # 增加判断条件，如果是私聊，直接可以响应，如果是群聊，必须引用或者@
        if message.is_chatroom:
            if message.local_type == MessageType.Text:
                if message.is_at:
                    pass
                else:
                    return
            elif message.local_type == MessageType.Quote:
                if message.quote_message and message.quote_message.is_self:
                    pass
                else:
                    return
            response = self.get_ai_response(msg=message, chat_history=chat_history)
            if message.local_type == MessageType.Quote:
                search_text = message.content
            else:
                search_text = f"{message.parsed_content.replace('\u2005', ' ').strip()}"
            plusginExcuteContext.add_response(
                PluginExcuteResponse(
                    message=message,
                    plugin_name=self.name,
                    should_stop=True,
                    actions=[
                        SendTextMessageAction(
                            content=response,
                            target=(
                                message.room.display_name
                                if message.room
                                else message.contact.display_name
                            ),
                            is_chatroom=message.is_chatroom,
                            at_user_name=None,
                            quote_message=search_text,
                            random_at_quote=True,  # 随机在@，引用，和不操作之间选择，在rpa里面有策略，实际上可以在操作的时候读取一下数据库，就会很方便
                        )
                    ],
                )
            )
        else:
            # 私聊的消息，直接使用Dify的工作流回复
            response = self.get_ai_response(msg=message, chat_history=chat_history)
            plusginExcuteContext.add_response(
                PluginExcuteResponse(
                    message=message,
                    plugin_name=self.name,
                    should_stop=True,
                    actions=[
                        SendTextMessageAction(
                            content=response,
                            target=(
                                message.room.display_name
                                if message.room
                                else message.contact.display_name
                            ),
                            is_chatroom=message.is_chatroom,
                        )
                    ],
                )
            )
        plusginExcuteContext.should_stop = True

    def get_plugin_name(self) -> str:
        return self.name

    def get_plugin_description(self) -> str:
        return "OpenAI 聊天机器人插件"

    @classmethod
    def get_plugin_config_schema(cls):
        return OpenAIBotPluginConfig