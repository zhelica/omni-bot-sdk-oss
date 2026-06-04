"""定时群发模式：knowledge（上岸知识点）| quiz（考公选择题）。"""

from __future__ import annotations

from typing import Any


def get_scheduled_broadcast_mode(config: Any) -> str:
    plugins = config.get("plugins") if hasattr(config, "get") else {}
    if not isinstance(plugins, dict):
        return "knowledge"
    mode = plugins.get("scheduled_broadcast_mode", "knowledge")
    if mode not in ("knowledge", "quiz"):
        return "knowledge"
    return mode


def is_scheduled_broadcast_mode(config: Any, mode: str) -> bool:
    return get_scheduled_broadcast_mode(config) == mode
