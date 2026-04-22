import importlib.metadata
import logging
import sys
from importlib import import_module
from pathlib import Path
from queue import Queue
from typing import TYPE_CHECKING, Dict, List, Tuple

# TYPE_CHECKING块仅用于类型提示，避免运行时循环依赖。
if TYPE_CHECKING:
    from omni_bot_sdk.bot import Bot
    from omni_bot_sdk.weixin.message_classes import Message

from omni_bot_sdk.plugins.core.plugin_interface import (
    Plugin,
    PluginExcuteContext,
    PluginExcuteResponse,
)

# 插件入口点组名，所有插件需注册到该组。
PLUGIN_ENTRY_POINT_GROUP = "omni_bot.plugins"


def _discover_plugins_from_file() -> List[Tuple[str, str]]:
    """
    Fallback: 直接从打包目录下的 omni_bot_sdk.egg-info/entry_points.txt 读取入口点。
    解决 PyInstaller 打包后 importlib.metadata 无法找到插件的问题。
    """
    candidates = []
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent

    egg_info_dir = base / "omni_bot_sdk.egg-info"
    entry_file = egg_info_dir / "entry_points.txt"

    logger = logging.getLogger(__name__)
    if not entry_file.exists():
        logger.info(f"[PluginDiscovery] entry_points.txt not found at {entry_file}, skipping fallback.")
        return []

    try:
        import configparser
    except ImportError:
        return []

    cfg = configparser.ConfigParser()
    try:
        with open(entry_file, encoding="utf-8") as f:
            cfg.read_file(f)
    except Exception as e:
        logger.error(f"[PluginDiscovery] 读取 entry_points.txt 失败: {e}")
        return []

    logger.info(f"[PluginDiscovery] cfg.sections()={cfg.sections()}")
    if PLUGIN_ENTRY_POINT_GROUP not in cfg:
        return []

    if PLUGIN_ENTRY_POINT_GROUP not in cfg:
        return []

    for name, value in cfg.items(PLUGIN_ENTRY_POINT_GROUP):
        value = value.strip()
        if not value or value.startswith("#"):
            continue
        if ":" not in value:
            continue
        candidates.append((name, value))
    logger.info(f"[PluginDiscovery] 从 egg-info 文件加载了 {len(candidates)} 个入口点。")
    return candidates


def _load_entry_point(value: str):
    """
    根据 entry_point 字符串 (如 "omni_bot_sdk.plugins.core.xxx:ClassName")
    动态加载并返回插件类。
    """
    if ":" not in value:
        return None
    module_path, class_name = value.rsplit(":", 1)
    try:
        module = import_module(module_path)
        cls = getattr(module, class_name.strip(), None)
        return cls
    except Exception:
        return None


class PluginManager:
    """
    插件管理器。
    负责插件的自动发现、加载、优先级排序、消息分发与热重载。
    """

    def __init__(self, bot: "Bot"):
        """
        初始化插件管理器。
        Args:
            bot (Bot): 主Bot实例，将注入到每个插件。
        """
        self.logger = logging.getLogger(__name__)
        self.bot = bot
        self.plugins: List[Plugin] = []

    def setup(self):
        """
        初始化并加载所有插件。
        """
        self.load_plugins()

    def load_plugins(self):
        """
        发现并加载所有已安装插件。
        支持插件启用/禁用配置，自动注入Bot实例。
        加载后按优先级排序。
        """
        self.logger.info(f"开始通过入口点组 '{PLUGIN_ENTRY_POINT_GROUP}' 加载插件...")

        plugins_config = self.bot.config.get("plugins", {})

        # 优先尝试标准 entry_points 方式（开发环境 / pip install -e）
        discovered = []
        try:
            eps = importlib.metadata.entry_points(group=PLUGIN_ENTRY_POINT_GROUP)
            try:
                discovered = list(eps)
            except TypeError:
                discovered = eps
        except Exception:
            discovered = []

        # fallback: 打包后从 omni_bot_sdk.egg-info/entry_points.txt 读取
        if not discovered:
            self.logger.info("标准 entry_points 未发现插件，尝试从 egg-info 文件读取...")
            file_eps = _discover_plugins_from_file()
            discovered = file_eps  # [(name, value), ...]

        if not discovered:
            self.logger.warning("未发现任何已安装的插件。请确保插件包已正确安装。")

        for entry_point in discovered:
            # 统一处理两种格式：标准 entry_points 对象 vs (name, value) 元组
            if isinstance(entry_point, tuple):
                plugin_id = entry_point[0]
                ep_value = entry_point[1]
                ep_name = plugin_id
            else:
                plugin_id = entry_point.name
                ep_value = entry_point.value
                ep_name = plugin_id

            try:
                plugin_conf = plugins_config.get(plugin_id, {})
                if (
                    isinstance(plugin_conf, dict)
                    and plugin_conf.get("enabled", False) is False
                ):
                    self.logger.info(f"插件 '{plugin_id}' 在配置中被禁用，跳过加载。")
                    continue

                self.logger.debug(
                    f"正在加载插件 '{plugin_id}' from '{ep_value}'..."
                )

                # 加载插件类
                if isinstance(entry_point, tuple):
                    plugin_class = _load_entry_point(ep_value)
                else:
                    plugin_class = entry_point.load()

                if plugin_class is None or not (
                    isinstance(plugin_class, type) and issubclass(plugin_class, Plugin)
                ):
                    self.logger.warning(
                        f"入口点 '{plugin_id}' 指向的对象不是有效的 Plugin 子类，已跳过。"
                    )
                    continue

                plugin_instance = plugin_class(self.bot)
                self.plugins.append(plugin_instance)
                self.logger.info(
                    f"成功加载并实例化插件: {plugin_instance.get_plugin_name()} (ID: {plugin_id})"
                )

            except Exception as e:
                self.logger.error(
                    f"加载插件 '{plugin_id}' 时发生错误: {e}", exc_info=True
                )

        # 按插件优先级降序排序
        self.plugins.sort(key=lambda p: getattr(p, "priority", 0), reverse=True)

        if self.plugins:
            plugin_order = " -> ".join([p.get_plugin_name() for p in self.plugins])
            self.logger.info(f"插件加载完成，执行顺序: {plugin_order}")
        else:
            self.logger.info("插件加载完成，但没有活动的插件。")

    async def process_message(
        self, message: "Message", context: Dict
    ) -> List[PluginExcuteResponse]:
        """
        异步处理消息，依次调用每个插件的 async handle_message 方法。
        支持should_stop机制，遇到插件中断链路时提前终止。
        """
        excute_context = PluginExcuteContext(message, context)
        for plugin in self.plugins:
            try:
                await plugin.handle_message(excute_context)
                self.logger.debug(f"插件 '{plugin.get_plugin_name()}' 处理完成。")
                if excute_context.should_stop:
                    self.logger.info(
                        f"插件 '{plugin.get_plugin_name()}' 停止了消息链的后续处理。"
                    )
                    break
            except Exception as e:
                self.logger.error(
                    f"插件 '{plugin.get_plugin_name()}' 处理消息时出错: {e}",
                    exc_info=True,
                )
                excute_context.add_error(plugin.get_plugin_name(), str(e))
        self.logger.info(f"插件处理消息完成")
        return excute_context.get_responses()

    def reload_all_plugins(self):
        """
        重新加载所有插件。
        清空当前插件实例列表并重新发现、加载。
        """
        self.logger.info("开始重新加载所有插件...")
        self.plugins.clear()
        self.load_plugins()
        self.logger.info("插件热重载完成。")
