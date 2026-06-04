"""
考公选择题定时发群：从公考题库接口抽题，延迟后按 id 查询答案与解析。
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, time as dt_time, timedelta
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from omni_bot_sdk.plugins.core.gongkao_xingce_client import (
    DEFAULT_API_BASE,
    GongkaoQuestion,
    GongkaoXingceClient,
    format_answer_message,
    format_question_message,
)
from omni_bot_sdk.plugins.core.plugin_interface import (
    Plugin,
    PluginExcuteContext,
)
from omni_bot_sdk.plugins.core.scheduled_broadcast import is_scheduled_broadcast_mode
from omni_bot_sdk.rpa.action_handlers import SendTextMessageAction


class ScheduledCivilServiceQuizPluginConfig(BaseModel):
    """考公选择题定时插件配置。"""

    enabled: bool = False
    target_chat_name: str = "济南人才交流群"
    morning_hours: List[int] = Field(default_factory=lambda: [9, 10, 11])
    afternoon_hours: List[int] = Field(default_factory=lambda: [14, 15, 16, 17])
    interval_minutes: int = 10
    answer_delay_seconds: int = 60
    question_prefix: str = "考公练题\n"
    answer_prefix: str = "参考答案\n"
    api_base_url: str = DEFAULT_API_BASE
    api_timeout_seconds: float = 15.0
    # 定时任务固定分类（1-6），留空则全库随机
    category: str = ""

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

    @field_validator("answer_delay_seconds")
    @classmethod
    def _answer_delay_valid(cls, v: int) -> int:
        if v < 1:
            raise ValueError("answer_delay_seconds must be >= 1")
        return v

    def merged_hours(self) -> List[int]:
        return sorted(set(self.morning_hours + self.afternoon_hours))

    def broadcast_minutes(self) -> List[int]:
        return list(range(0, 60, self.interval_minutes))

    def scheduled_category(self) -> Optional[str]:
        c = str(self.category).strip()
        return c if c else None


class ScheduledCivilServiceQuizPlugin(Plugin):
    """在配置时段内定时从接口抽题，延迟后按 id 拉取答案与解析。"""

    priority = 49
    name = "scheduled-civil-service-quiz-plugin"

    def __init__(self, bot):
        super().__init__(bot)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_fired: Optional[tuple] = None
        self._last_question_id: Optional[int] = None
        cfg = self.plugin_config
        self._client = GongkaoXingceClient(
            api_base_url=cfg.api_base_url,
            timeout=cfg.api_timeout_seconds,
        )
        if self.plugin_config.enabled and is_scheduled_broadcast_mode(
            self.config, "quiz"
        ):
            self._thread = threading.Thread(
                target=self._scheduler_loop,
                name="ScheduledCivilServiceQuiz",
                daemon=True,
            )
            self._thread.start()
            cat = cfg.scheduled_category()
            self.logger.info(
                "已启用考公选择题定时：目标群「%s」，每 %s 分钟发题，%s 秒后按 id 发解析，"
                "接口 %s，分类 %s",
                cfg.target_chat_name,
                cfg.interval_minutes,
                cfg.answer_delay_seconds,
                cfg.api_base_url,
                cat or "随机",
            )

    def _fetch_question(self) -> Optional[GongkaoQuestion]:
        cat = self.plugin_config.scheduled_category()
        return self._client.fetch_random(category=cat)

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
                    candidate = datetime.combine(
                        day, dt_time(hour=h, minute=m, second=0)
                    )
                    if candidate > now:
                        return candidate
        return now + timedelta(hours=24)

    def _interruptible_sleep(self, seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if self._stop.wait(min(60.0, remaining)):
                return True
        return False

    def _enqueue_text(self, content: str) -> None:
        action = SendTextMessageAction(
            content=content,
            target=self.plugin_config.target_chat_name,
            is_chatroom=True,
            at_user_name=None,
            quote_message=None,
            random_at_quote=False,
        )
        self.add_rpa_action(action)

    def _scheduler_loop(self):
        log = logging.getLogger(__name__)
        cfg = self.plugin_config
        while not self._stop.is_set():
            try:
                while not self.bot.is_running:
                    if self._stop.wait(2):
                        return

                now = datetime.now()
                nxt = self._next_fire_after(now)
                wait_s = max(1.0, (nxt - now).total_seconds())
                if self._interruptible_sleep(wait_s):
                    return

                slot_key = (nxt.date(), nxt.hour, nxt.minute)
                if slot_key == self._last_fired:
                    if self._stop.wait(2):
                        return
                    continue
                self._last_fired = slot_key

                question = self._fetch_question()
                if question is None:
                    log.warning("抽题失败，跳过本轮")
                    continue
                if question.id == self._last_question_id:
                    question = self._fetch_question()
                    if question is None:
                        continue
                self._last_question_id = question.id

                q_text = format_question_message(question, cfg.question_prefix)
                self._enqueue_text(q_text)
                log.info(
                    "考公题目已入队：%s id=%s → 「%s」",
                    nxt.strftime("%Y-%m-%d %H:%M"),
                    question.id,
                    cfg.target_chat_name,
                )

                if self._interruptible_sleep(float(cfg.answer_delay_seconds)):
                    return

                detail = self._client.fetch_by_id(question.id) or question
                a_text = format_answer_message(detail, cfg.answer_prefix)
                self._enqueue_text(a_text)
                log.info("考公答案已入队：id=%s 答案=%s", detail.id, detail.answer)
            except Exception as e:
                log.error("考公选择题定时线程异常: %s", e, exc_info=True)
                if self._stop.wait(60):
                    return

    async def handle_message(self, context: PluginExcuteContext) -> None:
        return

    def get_priority(self) -> int:
        return self.priority

    def get_plugin_name(self) -> str:
        return self.name

    def get_plugin_description(self) -> str:
        return "定时从公考题库接口抽题，并按 id 返回参考答案与解析"

    @classmethod
    def get_plugin_config_schema(cls):
        return ScheduledCivilServiceQuizPluginConfig
