import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

import openai
from pydantic import BaseModel
from omni_bot_sdk.plugins.core.gongkao_xingce_client import (
    DEFAULT_API_BASE,
    GongkaoXingceClient,
    format_answer_message,
    format_question_message,
    is_draw_request,
    parse_draw_category,
)
from omni_bot_sdk.plugins.interface import (
    Bot,
    Plugin,
    PluginExcuteContext,
    PluginExcuteResponse,
    MessageType,
    SendTextMessageAction,
)
from omni_bot_sdk.weixin.message_classes import _contact_display_name, _contact_username


def _safe_str(value) -> str:
    """保证写入 prompt / API 的占位符与消息正文均为 str（避免 DB 整型 id 等导致 str.replace 报错）。"""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


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
    gongkao_api_base_url: str = DEFAULT_API_BASE
    gongkao_api_timeout_seconds: float = 15.0
    draw_answer_delay_seconds: int = 60
    draw_question_prefix: str = "考公练题\n"
    draw_answer_prefix: str = "参考答案\n"


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
        self._gongkao_client = GongkaoXingceClient(
            api_base_url=self.plugin_config.gongkao_api_base_url,
            timeout=self.plugin_config.gongkao_api_timeout_seconds,
        )

    def _get_context_key(self, msg) -> str:
        """生成会话上下文 key：群聊用 room_nickname，私聊用 contact_nickname"""
        if msg.is_chatroom:
            room_name = _safe_str(msg.room.display_name if msg.room else "")
            contact_name = _safe_str(msg.real_sender_id)
        else:
            room_name = ""
            contact_name = _contact_display_name(msg.contact) or _safe_str(
                msg.real_sender_id
            )
        return f"{room_name}:{contact_name}"

    def _get_or_create_context(self, msg) -> ConversationContext:
        key = self._get_context_key(msg)
        if key not in self._conversation_contexts:
            self._conversation_contexts[key] = ConversationContext(max_history=20)
        return self._conversation_contexts[key]

    def _message_plain_for_ai(self, msg) -> str:
        """
        用户侧正文，与 openai_bot_plugin_bak 一致只用 parsed_content。
        引用消息在工厂里 content 固定为 \"\"，必须用 parsed_content 才有字。
        """
        pc = msg.parsed_content
        if isinstance(pc, bytes):
            pc = pc.decode("utf-8", errors="replace")
        else:
            pc = pc or ""
        nick = _safe_str(self.user.nickname)
        return pc.replace(f"@{nick}", "").replace("\u2005", " ").strip()

    def _send_draw_answer_delayed(self, message, question_id: int) -> None:
        """延迟后按 id 查询解析并发送到当前会话。"""
        delay = float(self.plugin_config.draw_answer_delay_seconds)
        if self._interruptible_wait(delay):
            return
        detail = self._gongkao_client.fetch_by_id(question_id)
        if detail is None:
            self.logger.warning("抽题答案查询失败 id=%s", question_id)
            return
        text = format_answer_message(detail, self.plugin_config.draw_answer_prefix)
        self.add_rpa_action(
            SendTextMessageAction(
                content=text,
                target=message.target,
                is_chatroom=message.is_chatroom,
                at_user_name=None,
                quote_message=None,
                random_at_quote=False,
            )
        )
        self.logger.info("抽题答案已入队 id=%s", question_id)

    def _interruptible_wait(self, seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))
        return False

    def _handle_draw_question(self, message, content: str) -> Optional[str]:
        category = parse_draw_category(content)
        question = self._gongkao_client.fetch_random(category=category)
        if question is None:
            return "抽题失败，请稍后再试。"
        threading.Thread(
            target=self._send_draw_answer_delayed,
            args=(message, question.id),
            name=f"DrawAnswer-{question.id}",
            daemon=True,
        ).start()
        return format_question_message(
            question, self.plugin_config.draw_question_prefix
        )

    def get_ai_response(self, msg) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            content = self._message_plain_for_ai(msg)

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
            system_prompt = system_prompt.replace(
                "{{chat_history}}", _safe_str(chat_history or "")
            )
            system_prompt = system_prompt.replace("{{time_now}}", time_now)
            system_prompt = system_prompt.replace(
                "{{self_nickname}}", _safe_str(self.user.nickname)
            )
            system_prompt = system_prompt.replace(
                "{{room_nickname}}",
                _safe_str(msg.room.display_name if msg.room else ""),
            )

            # 查询发送者昵称（群聊里 real_sender_id 常为整型，不能与 wxid 字符串直接比较）
            sender_id = msg.real_sender_id
            for probe in (_safe_str(getattr(msg, "content", "")), content):
                if not probe:
                    continue
                content_sender_match = re.match(r"(wxid_\w+):", probe)
                if content_sender_match:
                    sender_id = content_sender_match.group(1)
                    break

            contact_nickname = ""
            sender_wxid: Optional[str] = None
            if isinstance(sender_id, str) and sender_id:
                sender_wxid = sender_id
            elif isinstance(sender_id, int) and sender_id:
                db_path = getattr(msg, "message_db_path", None)
                row_contact = self.bot.db.get_contact_by_sender_id(
                    sender_id, Path(db_path) if db_path else None
                )
                if row_contact:
                    sender_wxid = row_contact.username
                    contact_nickname = _safe_str(row_contact.display_name)

            if sender_wxid:
                if msg.room:
                    member_list = self.bot.db.get_room_member_list(msg.room.username)
                    for member in member_list:
                        if member.username == sender_wxid:
                            contact_nickname = _safe_str(member.display_name)
                            break
                elif not contact_nickname:
                    contact = self.bot.db.get_contact_by_username(sender_wxid)
                    if contact:
                        contact_nickname = _safe_str(contact.display_name)

            if not contact_nickname and sender_wxid:
                contact_nickname = sender_wxid

            system_prompt = system_prompt.replace(
                "{{contact_nickname}}", _safe_str(contact_nickname)
            )
            self.logger.info(f"system_prompt: {system_prompt}")
            self.logger.info(f"会话上下文 key={context_key}, 当前历史条数={len(ctx._history)}, 内容={chat_history}")

            messages = []
            messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": _safe_str(content)})
            response = openai.chat.completions.create(
                model=self.model,
                messages=messages,
                user=(
                    msg.room.username
                    if msg.is_chatroom
                    else (_contact_username(msg.contact) or "")
                ),
            )
            raw = response.choices[0].message.content
            answer = _safe_str(raw).strip()

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
            content = self._message_plain_for_ai(message)
            if is_draw_request(content):
                response = self._handle_draw_question(message, content)
            else:
                response = self.get_ai_response(msg=message)
            if response is None or not str(response).strip():
                self.logger.warning("AI 无有效回复，跳过发送")
                return
            search_text = self._message_plain_for_ai(message)
            plusginExcuteContext.add_response(
                PluginExcuteResponse(
                    message=message,
                    plugin_name=self.name,
                    should_stop=True,
                    actions=[
                        SendTextMessageAction(
                            content=response,
                            target=message.target,
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
