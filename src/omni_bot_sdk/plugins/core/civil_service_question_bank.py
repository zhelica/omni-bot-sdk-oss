"""兼容导出：公考题库请使用 gongkao_xingce_client。"""

from omni_bot_sdk.plugins.core.gongkao_xingce_client import (
    DEFAULT_API_BASE,
    GongkaoQuestion,
    GongkaoXingceClient,
    apply_content_prefix,
    format_answer_message,
    format_question_message,
    is_draw_request,
    parse_draw_category,
)

# 旧名兼容
CivilServiceQuestion = GongkaoQuestion

__all__ = [
    "DEFAULT_API_BASE",
    "CivilServiceQuestion",
    "GongkaoQuestion",
    "GongkaoXingceClient",
    "apply_content_prefix",
    "format_answer_message",
    "format_question_message",
    "is_draw_request",
    "parse_draw_category",
]
