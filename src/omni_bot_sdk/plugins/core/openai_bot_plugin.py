import re
import time
from collections import OrderedDict
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

    enabled: bool = False
    openai_api_key: str = "unknown"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-3.5-turbo"
    priority: int = 100
    prompt: str = (
        "你是一个聊天机器人，请根据用户的问题给出回答。历史对话：{{chat_history}} 当前时间：{{time_now}} "
        "你的昵称：{{self_nickname}} 群昵称：{{room_nickname}} 用户昵称是：{{contact_nickname}}，你可以称呼他的昵称"
    )


class ConversationContext:
    """
    单个会话的上下文历史，按 room_nickname:contact_nickname 索引。
    使用 OrderedDict 保持顺序，最多保留 MAX_HISTORY 条。
    """

    def __init__(self, max_history: int = 20):
        self.max_history = max_history
        # 有序字典：key 为 msg.server_id，value 为 {"role": "user"/"assistant", "content": str}
        self._history: OrderedDict[str, dict] = OrderedDict()

    def add_user(self, server_id: str, content: str):
        """添加用户消息"""
        self._add(server_id, "user", content)

    def add_assistant(self, server_id: str, content: str):
        """添加 AI 回复"""
        self._add(server_id, "assistant", content)

    def _add(self, server_id: str, role: str, content: str):
        self._history[server_id] = {"role": role, "content": content}
        # 超过上限时移除最旧的消息
        while len(self._history) > self.max_history:
            self._history.popitem(last=False)

    def get_history(self) -> str:
        """将历史消息格式化为文本，用于填充 {{chat_history}} 占位符"""
        if not self._history:
            return ""
        lines = []
        for item in self._history.values():
            role_prefix = "用户" if item["role"] == "user" else "AI"
            lines.append(f"{role_prefix}：{item['content']}")
        return "\n".join(lines)

    def clear(self):
        """清空历史"""
        self._history.clear()


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
        # 会话上下文，按 room_nickname:contact_nickname 索引
        self._conversation_contexts: dict[str, ConversationContext] = {}

    def _get_context_key(self, msg) -> str:
        """生成会话上下文 key：群聊用 room_nickname，私聊用 contact_nickname"""
        if msg.is_chatroom:
            room_name = msg.room.display_name if msg.room else ""
            contact_name = msg.real_sender_id or ""
        else:
            room_name = ""
            contact_name = msg.contact.display_name if msg.contact else msg.real_sender_id or ""
        return f"{room_name}:{contact_name}"

    def _get_or_create_context(self, msg) -> ConversationContext:
        key = self._get_context_key(msg)
        if key not in self._conversation_contexts:
            self._conversation_contexts[key] = ConversationContext(max_history=20)
        return self._conversation_contexts[key]

    def get_ai_response(self, msg) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            if msg.local_type == MessageType.Quote:
                content = msg.content
            else:
                content = msg.content
                # content = (
                #     msg.parsed_content.replace(f"@{self.user.nickname}", "")
                #     .replace("\u2005", "")
                #     .strip()
                # )

            time_now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

            # 获取当前会话上下文 key
            context_key = self._get_context_key(msg)
            ctx = self._get_or_create_context(msg)

            # 先把用户消息加入历史（server_id 作为唯一 key 防止重复）
            server_id = str(msg.server_id) if msg.server_id else f"user_{time.time()}"
            ctx.add_user(server_id, content)

            # 获取历史对话
            chat_history = ctx.get_history()

            # 构建 system_prompt
            system_prompt = self.prompt
            system_prompt = system_prompt.replace("{{chat_history}}", chat_history or "")
            system_prompt = system_prompt.replace("{{time_now}}", time_now)
            system_prompt = system_prompt.replace("{{self_nickname}}", self.user.nickname)
            system_prompt = system_prompt.replace(
                "{{room_nickname}}", msg.room.display_name if msg.room else ""
            )

            # 查询发送者昵称
            sender_id = msg.real_sender_id
            content_sender_match = re.match(r"(wxid_\w+):", msg.content)
            if content_sender_match:
                sender_id = content_sender_match.group(1)
            contact_nickname = sender_id or ""
            if sender_id:
                if msg.room:
                    member_list = self.bot.db.get_room_member_list(msg.room.username)
                    for member in member_list:
                        if member.username == sender_id:
                            contact_nickname = member.display_name
                            break
                else:
                    contact = self.bot.db.get_contact_by_username(sender_id)
                    if contact:
                        contact_nickname = contact.display_name

            system_prompt = system_prompt.replace("{{contact_nickname}}", contact_nickname)
            self.logger.info(f"system_prompt: {system_prompt}")
            self.logger.info(f"会话上下文 key={context_key}, 当前历史条数={len(ctx._history)}, 内容={chat_history}")

            messages = []
            messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": content})

            # 通过 WebSocket 发送消息给外部 AI 服务
            import uuid
            room_nickname = msg.room.display_name if msg.room else ""
            event_id = str(uuid.uuid4())
            ws_message = {
                "event_id": event_id,
                "event": {
                    "msg_type": 1,  # 1-文本消息
                    "room_id": msg.room.username if msg.is_chatroom else "",
                    "room_nickname": room_nickname,
                    "contact_nickname": contact_nickname,
                    "self_nickname": self.user.nickname,
                    "chat_history": chat_history,
                    "time_now": time_now,
                    "server_id": server_id,
                    "content": content,
                    "sender_id": sender_id,
                    "guid": "123"
                }
            }

            if self.bot.websocket_service:
                self.bot.websocket_service.broadcast(ws_message)
                self.logger.info(f"已通过 WebSocket 发送消息: {ws_message}")

            # 等待外部 AI 服务的响应（暂时返回空，由外部服务通过其他方式回复）
            answer = ""

            # 把 AI 回复也加入历史
            assistant_id = f"assistant_{time.time()}"
            ctx.add_assistant(assistant_id, answer)

            return answer
        except Exception as e:
            self.logger.error(f"获取AI响应时出错: {e}")
            return None

    def get_priority(self) -> int:
        return self.priority

    async def handle_message(self, plusginExcuteContext: PluginExcuteContext) -> None:
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
        if not_for_bot:
            return
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
            response = self.get_ai_response(msg=message)
            if not response:
                # 消息已通过 WebSocket 发送，等待外部 AI 服务响应
                self.logger.info("消息已通过 WebSocket 发送，等待外部 AI 响应")
                return
            search_text = message.content
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
                            random_at_quote=True,
                        )
                    ],
                )
            )
        else:
            return
        plusginExcuteContext.should_stop = True

    def get_plugin_name(self) -> str:
        return self.name

    def get_plugin_description(self) -> str:
        return "OpenAI 聊天机器人插件"

    @classmethod
    def get_plugin_config_schema(cls):
        return OpenAIBotPluginConfig
