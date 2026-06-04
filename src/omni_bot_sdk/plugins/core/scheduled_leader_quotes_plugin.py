"""
在指定时段内向群聊随机发送话术（可配置间隔分钟、内容前缀与群名）。
"""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, time as dt_time, timedelta
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from omni_bot_sdk.plugins.core.plugin_interface import (
    Plugin,
    PluginExcuteContext,
)
from omni_bot_sdk.plugins.core.leader_quotes_phrases import default_leader_phrases
from omni_bot_sdk.plugins.core.scheduled_broadcast import is_scheduled_broadcast_mode
from omni_bot_sdk.rpa.action_handlers import SendTextMessageAction


class ScheduledLeaderQuotesPluginConfig(BaseModel):
    """定时领导原话插件配置。"""

    enabled: bool = False
    target_chat_name: str = "济南人才交流群"
    morning_hours: List[int] = Field(default_factory=lambda: [9, 10, 11])
    afternoon_hours: List[int] = Field(default_factory=lambda: [14, 15, 16, 17])
    interval_minutes: int = 60
    content_prefix: str = ""
    phrases: Optional[List[str]] = None

    @field_validator("morning_hours", "afternoon_hours")
    @classmethod
    def _hours_in_day(cls, v: List[int]) -> List[int]:
        for h in v:
            if h < 0 or h > 23:
                raise ValueError("hour must be 0-23")
        return v

    @field_validator("interval_minutes")
    @classmethod
    def _interval_minutes_valid(cls, v: int) -> int:
        if v < 1 or v > 60 or 60 % v != 0:
            raise ValueError("interval_minutes must divide 60 evenly (1-60)")
        return v

    def merged_hours(self) -> List[int]:
        return sorted(set(self.morning_hours + self.afternoon_hours))

    def broadcast_minutes(self) -> List[int]:
        return list(range(0, 60, self.interval_minutes))

    def format_message(self, phrase: str) -> str:
        prefix = self.content_prefix
        if not prefix:
            return phrase
        if prefix.endswith("：") or prefix.endswith(":"):
            prefix = prefix[:-1] + "\n"
        if phrase.startswith(prefix):
            return phrase
        return prefix + phrase


class ScheduledLeaderQuotesPlugin(Plugin):
    """
    在配置的时段内，按 interval_minutes 间隔随机选一句发送到目标群（群显示名需与 window_manager 切换会话一致）。
    """

    priority = 50
    name = "scheduled-leader-quotes-plugin"

    def __init__(self, bot):
        super().__init__(bot)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_fired: Optional[tuple] = None
        if self.plugin_config.enabled and is_scheduled_broadcast_mode(
            self.config, "knowledge"
        ):
            self._thread = threading.Thread(
                target=self._scheduler_loop, name="ScheduledLeaderQuotes", daemon=True
            )
            self._thread.start()
            self.logger.info(
                "已启用定时领导原话：目标群「%s」，每 %s 分钟，小时 %s",
                self.plugin_config.target_chat_name,
                self.plugin_config.interval_minutes,
                self.plugin_config.merged_hours(),
            )

    def _phrases(self) -> list[str]:
        cfg = self.plugin_config
        if cfg.phrases:
            return [p.strip() for p in cfg.phrases if p and str(p).strip()]
        return default_leader_phrases()

    def _next_fire_after(self, now: datetime) -> datetime:
        hours = self.plugin_config.merged_hours()
        minutes = self.plugin_config.broadcast_minutes()
        if not hours:
            return now + timedelta(hours=24)
        base = now.replace(second=0, microsecond=0)
        for day_off in range(3):
            day = (base + timedelta(days=day_off)).date()
            for h in hours:
                for m in minutes:
                    candidate = datetime.combine(day, dt_time(hour=h, minute=m, second=0))
                    if candidate > now:
                        return candidate
        return now + timedelta(hours=24)

    def _interruptible_sleep(self, seconds: float) -> bool:
        """睡眠指定秒数，可被 _stop 打断。返回 True 表示应退出调度线程。"""
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if self._stop.wait(min(60.0, remaining)):
                return True
        return False

    def _scheduler_loop(self):
        log = logging.getLogger(__name__)
        while not self._stop.is_set():
            try:
                while not self.bot.is_running:
                    if self._stop.wait(2):
                        return
                phrases = self._phrases()
                if not phrases:
                    log.warning("领导原话列表为空，定时任务休眠 1 小时")
                    if self._stop.wait(3600):
                        return
                    continue

                now = datetime.now()
                nxt = self._next_fire_after(now)
                wait_s = max(1.0, (nxt - now).total_seconds())
                if self._interruptible_sleep(wait_s):
                    return

                phrases = self._phrases()
                if not phrases:
                    continue

                slot_key = (nxt.date(), nxt.hour, nxt.minute)
                if slot_key == self._last_fired:
                    if self._stop.wait(2):
                        return
                    continue
                self._last_fired = slot_key

                text = self.plugin_config.format_message(random.choice(phrases))
                action = SendTextMessageAction(
                    content=text,
                    target=self.plugin_config.target_chat_name,
                    is_chatroom=True,
                    at_user_name=None,
                    quote_message=None,
                    random_at_quote=False,
                )
                self.add_rpa_action(action)
                log.info(
                    "定时领导原话已入队：%s → 「%s」",
                    nxt.strftime("%Y-%m-%d %H:%M"),
                    self.plugin_config.target_chat_name,
                )
            except Exception as e:
                log.error("定时领导原话线程异常: %s", e, exc_info=True)
                if self._stop.wait(60):
                    return

    async def handle_message(self, context: PluginExcuteContext) -> None:
        return

    def get_priority(self) -> int:
        return self.priority

    def get_plugin_name(self) -> str:
        return self.name

    def get_plugin_description(self) -> str:
        return "在指定时段按间隔向群随机发送话术（可配置内容前缀）"

    @classmethod
    def get_plugin_config_schema(cls):
        return ScheduledLeaderQuotesPluginConfig
