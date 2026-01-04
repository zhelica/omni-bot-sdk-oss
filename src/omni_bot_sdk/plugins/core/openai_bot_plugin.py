import time
from typing import Optional
import re
import requests
import json

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
    自定义 API Bot 插件配置
    enabled: 是否启用该插件
    api_url: 自定义API接口地址
    api_key: API密钥（如果需要）
    timeout: 请求超时时间（秒）
    priority: 插件优先级，数值越大优先级越高
    """

    enabled: bool = True
    api_url: str = "https://qibaozhai.top/prod-api/wechat/msg/rpaMsg"
    api_key: str = ""
    timeout: int = 70
    priority: int = 100


class OpenAIBotPlugin(Plugin):
    """
    自定义 API 聊天机器人插件实现类
    """

    priority = 100
    name = "openai-bot-plugin"

    def __init__(self, bot: "Bot"):
        super().__init__(bot)
        self.api_url = self.plugin_config.api_url
        self.api_key = self.plugin_config.api_key
        self.timeout = self.plugin_config.timeout
        self.enabled = self.plugin_config.enabled
        self.priority = getattr(self.plugin_config, "priority", self.__class__.priority)
        self.user = bot.user_info

    def get_ai_response(self, msg) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            # 清理消息内容
            content = (
                msg.parsed_content.replace(f"@{self.user.nickname}", "")
                .replace("\u2005", "")
                .strip()
            )

            # 提取模板信息
            parsed_content = msg.parsed_content.replace('\u2005', ' ').strip()
            # 构造请求数据
            request_data = {
                "data":{
                    "parsed_content": parsed_content
                }
            }
            self.logger.info(f"请求数据: {request_data}")
            # 调用自定义API接口
            headers = {"Content-Type": "application/json"}
            self.logger.info(f"调用自定义API: {self.api_url}")
            self.logger.info(f"请求数据: {request_data}")

            response = requests.post(
                self.api_url,
                json=request_data,
                headers=headers,
                timeout=self.timeout
            )

            if response.status_code == 200:
                result = response.json()
                # 假设API返回格式为 {"success": true, "message": "处理结果"}
                return result.get("msg")
            else:
                self.logger.error(f"API调用失败，状态码: {response.status_code}, 响应: {response.text}")
                return f"API调用失败: {response.status_code}"

        except requests.exceptions.Timeout:
            self.logger.error(f"API调用超时: {self.timeout}秒")
            return "API调用超时，请稍后重试"
        except requests.exceptions.RequestException as e:
            self.logger.error(f"API调用网络错误: {e}")
            return "网络连接错误，请检查API服务状态"
        except Exception as e:
            self.logger.error(f"处理消息时出错: {e}")
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
        self.logger.info(f" 消息类型: {message.local_type}, {message.message_content}")
        if message.local_type != MessageType.Text:
            return
        context = plusginExcuteContext.get_context()
        not_for_bot = context.get("not_for_bot", False)
        if not_for_bot:
            return

        if message.is_chatroom:
            if message.local_type == MessageType.Text:
                if not message.is_mention_chat_only:
                # if not message.is_at:
                    return
            elif message.local_type == MessageType.Quote:
                if not (message.quote_message and message.quote_message.is_self):
                    return
            else:
                return

            # 获取响应内容
            response = self.get_ai_response(msg=message)
            search_text = f"{message.parsed_content.replace('\u2005', ' ').strip()}"
            # 回复消息
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
        plusginExcuteContext.should_stop = True

    def get_plugin_name(self) -> str:
        return self.name

    def get_plugin_description(self) -> str:
        return "自定义 API 聊天机器人插件"

    @classmethod
    def get_plugin_config_schema(cls):
        return OpenAIBotPluginConfig
