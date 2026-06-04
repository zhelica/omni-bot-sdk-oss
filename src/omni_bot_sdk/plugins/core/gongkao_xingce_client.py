"""
公考行测题库 HTTP 接口客户端。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

DEFAULT_API_BASE = "http://218.244.140.247/prod-api"

# 分类名 -> category 参数（接口键值）
CATEGORY_NAME_TO_ID: Dict[str, str] = {
    "政治理论": "1",
    "常识判断": "2",
    "言语理解与表达": "3",
    "数量关系": "4",
    "判断推理": "5",
    "资料分析": "6",
}

_DRAW_KEYWORD = "抽题"
_ANALYSIS_NOISE = re.compile(
    r"公公务务员员|\.iinndddd|决战行测\d+题|220\d{2}/\d+/\d+"
)


@dataclass(frozen=True)
class GongkaoQuestion:
    id: int
    category: str
    title: str
    options: Dict[str, str]
    answer: str
    analysis: str


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value).strip()


def _clean_analysis(text: str) -> str:
    lines: List[str] = []
    for line in _safe_str(text).splitlines():
        if _ANALYSIS_NOISE.search(line):
            continue
        line = line.strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def question_from_api_data(data: dict) -> GongkaoQuestion:
    return GongkaoQuestion(
        id=int(data["id"]),
        category=_safe_str(data.get("category")),
        title=_safe_str(data.get("title")),
        options={
            "A": _safe_str(data.get("optionA")),
            "B": _safe_str(data.get("optionB")),
            "C": _safe_str(data.get("optionC")),
            "D": _safe_str(data.get("optionD")),
        },
        answer=_safe_str(data.get("answer")),
        analysis=_safe_str(data.get("analysis")),
    )


def apply_content_prefix(prefix: str, body: str) -> str:
    if not prefix:
        return body
    p = prefix
    if p.endswith("：") or p.endswith(":"):
        p = p[:-1] + "\n"
    if body.startswith(p):
        return body
    return p + body


def format_question_message(q: GongkaoQuestion, prefix: str = "") -> str:
    lines = [q.title]
    for key in ("A", "B", "C", "D"):
        opt = q.options.get(key, "")
        if opt:
            lines.append(f"{key}. {opt}")
    return apply_content_prefix(prefix, "\n".join(lines))


def format_answer_message(q: GongkaoQuestion, prefix: str = "") -> str:
    analysis = _clean_analysis(q.analysis)
    body = f"答案：{q.answer}"
    if analysis:
        body = f"{body}\n{analysis}"
    return apply_content_prefix(prefix, body)


def is_draw_request(text: str) -> bool:
    return _DRAW_KEYWORD in _safe_str(text)


def parse_draw_category(text: str) -> Optional[str]:
    """
    从用户消息解析分类 id。
    须包含「抽题」；匹配到分类名则返回 id；仅有抽题无分类则返回 None（表示全库随机）。
    """
    compact = re.sub(r"\s+", "", _safe_str(text))
    if _DRAW_KEYWORD not in compact:
        return None
    matched: List[tuple[int, str]] = []
    for name, cid in CATEGORY_NAME_TO_ID.items():
        name_compact = re.sub(r"\s+", "", name)
        if name_compact in compact:
            matched.append((len(name_compact), cid))
    if not matched:
        return None
    matched.sort(key=lambda x: x[0], reverse=True)
    return matched[0][1]


class GongkaoXingceClient:
    def __init__(self, api_base_url: str = DEFAULT_API_BASE, timeout: float = 15.0):
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

    def _get(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        url = f"{self.api_base_url}{path}"
        try:
            resp = requests.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            self.logger.error("公考题库请求失败 %s: %s", url, e, exc_info=True)
            return None
        if payload.get("code") != 200:
            self.logger.warning(
                "公考题库返回异常 code=%s msg=%s",
                payload.get("code"),
                payload.get("msg"),
            )
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        return data

    def fetch_random(self, category: Optional[str] = None) -> Optional[GongkaoQuestion]:
        if category:
            data = self._get(
                "/gongKao/xingce/random/category", params={"category": category}
            )
        else:
            data = self._get("/gongKao/xingce/random")
        if not data:
            return None
        return question_from_api_data(data)

    def fetch_by_id(self, question_id: int) -> Optional[GongkaoQuestion]:
        data = self._get(f"/gongKao/xingce/{question_id}")
        if not data:
            return None
        return question_from_api_data(data)
