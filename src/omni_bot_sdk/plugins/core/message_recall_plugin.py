"""
消息撤回插件。
通过接口调用，实现微信消息的自动化撤回功能。
"""

import logging
from typing import TYPE_CHECKING, List, Optional
from pydantic import BaseModel

from omni_bot_sdk.plugins.interface import Plugin, PluginExcuteContext
from omni_bot_sdk.rpa.message_recall import MessageRecallController

if TYPE_CHECKING:
    from omni_bot_sdk.bot import Bot


class MessageRecallConfig(BaseModel):
    """
    消息撤回插件配置
    enabled: 是否启用该插件
    priority: 插件优先级，数值越大优先级越高
    default_similarity: 默认相似度阈值
    default_retries: 默认重试次数
    """
    enabled: bool = False
    priority: int = 900
    default_similarity: float = 0.6
    default_retries: int = 2


class MessageRecallPlugin(Plugin):
    """
    消息撤回插件。
    提供通过接口调用实现微信消息撤回的能力。
    """

    priority = 900
    name = "message-recall-plugin"

    def __init__(self, bot: "Bot" = None):
        super().__init__(bot)
        self.priority = getattr(self.plugin_config, "priority", self.__class__.priority)
        self._recall_controller = None
        self._window_manager = None

    def get_priority(self) -> int:
        return self.priority

    def _get_recall_controller(self) -> Optional[MessageRecallController]:
        """
        获取消息撤回控制器实例。
        Returns:
            MessageRecallController实例，如果不可用返回None
        """
        try:
            # 尝试从bot获取window_manager
            if self._window_manager is None:
                # 检查bot是否有window_manager属性
                if hasattr(self.bot, 'window_manager'):
                    self._window_manager = self.bot.window_manager
                elif hasattr(self.bot, 'rpa_service') and hasattr(self.bot.rpa_service, 'window_manager'):
                    self._window_manager = self.bot.rpa_service.window_manager
                elif hasattr(self.bot, 'processor_service') and hasattr(self.bot.processor_service, 'window_manager'):
                    self._window_manager = self.bot.processor_service.window_manager

            if self._window_manager:
                if self._recall_controller is None:
                    self._recall_controller = MessageRecallController(self._window_manager)
                return self._recall_controller

            return None

        except Exception as e:
            self.logger.error(f"获取撤回控制器失败: {str(e)}")
            return None

    def recall_message(
        self,
        contact_name: str,
        message_text: str = None,
        keyword: str = None,
        recall_latest: bool = False,
        similarity: float = None,
        max_retries: int = None,
    ) -> dict:
        """
        撤回消息的核心方法。

        Args:
            contact_name: 联系人名称
            message_text: 要撤回的消息内容（精确匹配）
            keyword: 关键词（模糊匹配），当message_text为空时使用
            recall_latest: 是否撤回最新消息
            similarity: 相似度阈值
            max_retries: 最大重试次数

        Returns:
            dict: 撤回结果 {"success": bool, "message": str}
        """
        controller = self._get_recall_controller()

        if not controller:
            return {
                "success": False,
                "message": "消息撤回控制器不可用，请确保RPA服务已初始化"
            }

        # 使用默认值
        if similarity is None:
            similarity = self.plugin_config.default_similarity
        if max_retries is None:
            max_retries = self.plugin_config.default_retries

        try:
            if recall_latest:
                # 撤回最新消息
                self.logger.info(f"撤回 {contact_name} 的最新消息")
                success = controller.recall_latest_message(
                    contact_name=contact_name,
                    max_retries=max_retries,
                )
                return {
                    "success": success,
                    "message": "最新消息撤回成功" if success else "最新消息撤回失败"
                }

            elif message_text:
                # 通过消息内容撤回
                self.logger.info(f"撤回 {contact_name} 中包含 '{message_text}' 的消息")
                success = controller.recall_by_text(
                    contact_name=contact_name,
                    message_text=message_text,
                    similarity_threshold=similarity,
                    max_retries=max_retries,
                )
                return {
                    "success": success,
                    "message": "消息撤回成功" if success else "消息撤回失败"
                }

            elif keyword:
                # 通过关键词撤回
                self.logger.info(f"撤回 {contact_name} 中包含关键词 '{keyword}' 的消息")
                success = controller.recall_by_keyword(
                    contact_name=contact_name,
                    keyword=keyword,
                    max_retries=max_retries,
                )
                return {
                    "success": success,
                    "message": "关键词消息撤回成功" if success else "关键词消息撤回失败"
                }

            else:
                return {
                    "success": False,
                    "message": "请提供 message_text、keyword 或设置 recall_latest=True"
                }

        except Exception as e:
            self.logger.error(f"撤回消息出错: {str(e)}")
            return {
                "success": False,
                "message": f"撤回出错: {str(e)}"
            }

    def recall_multiple(
        self,
        contact_name: str,
        keyword: str,
        max_count: int = 10,
        interval: float = 1.0,
    ) -> dict:
        """
        批量撤回匹配关键词的消息。

        Args:
            contact_name: 联系人名称
            keyword: 关键词
            max_count: 最大撤回数量
            interval: 每次撤回间隔（秒）

        Returns:
            dict: 撤回结果
        """
        controller = self._get_recall_controller()

        if not controller:
            return {
                "success": False,
                "message": "消息撤回控制器不可用",
                "count": 0
            }

        try:
            count = controller.recall_multiple_by_keyword(
                contact_name=contact_name,
                keyword=keyword,
                max_count=max_count,
                interval=interval,
            )
            return {
                "success": count > 0,
                "message": f"成功撤回 {count} 条消息",
                "count": count
            }
        except Exception as e:
            self.logger.error(f"批量撤回出错: {str(e)}")
            return {
                "success": False,
                "message": f"批量撤回出错: {str(e)}",
                "count": 0
            }

    async def handle_message(self, context: PluginExcuteContext) -> None:
        """
        处理消息的异步方法。
        注意：此插件主要用于接口调用，不拦截普通消息。
        """
        message = context.get_message()

        # 检查是否是撤回指令
        content = message.content.strip() if hasattr(message, 'content') else ""

        # 如果是撤回指令，执行撤回
        if content.startswith("!recall") or content.startswith("撤回"):
            self.logger.info(f"收到撤回指令: {content}")

            parts = content.split()
            if len(parts) >= 2:
                # 解析命令
                command = parts[0]
                args_part = " ".join(parts[1:])

                # 支持多种格式：
                # !recall 联系人 消息内容
                # !recall latest 联系人
                # 撤回 联系人 关键词

                if "latest" in args_part.lower():
                    # 撤回最新消息
                    contact = args_part.lower().replace("latest", "").strip()
                    result = self.recall_message(contact_name=contact, recall_latest=True)
                else:
                    # 格式: 联系人 消息内容/关键词
                    # 尝试分离联系人名称和消息内容
                    # 假设第一个空格前是联系人
                    space_idx = args_part.find(" ")
                    if space_idx > 0:
                        contact = args_part[:space_idx]
                        content_to_find = args_part[space_idx + 1:]
                        result = self.recall_message(
                            contact_name=contact,
                            message_text=content_to_find
                        )
                    else:
                        result = {
                            "success": False,
                            "message": "格式错误，请使用: !recall 联系人 消息内容"
                        }

                self.logger.info(f"撤回结果: {result}")

    def get_plugin_name(self) -> str:
        return self.name

    def get_plugin_description(self) -> str:
        return "消息撤回插件，支持通过接口调用撤回微信消息"

    @classmethod
    def get_plugin_config_schema(cls):
        """
        返回插件配置的pydantic schema类。
        """
        return MessageRecallConfig
