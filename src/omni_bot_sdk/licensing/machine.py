"""本机机器码（用于秘钥绑定）。"""

from __future__ import annotations

import hashlib
import re


def get_machine_code() -> str:
    """
    生成稳定机器码（大写十六进制，便于发给发卡方）。
    优先 py-machineid；失败则回退到主机名+MAC 的摘要。
    """
    raw = ""
    try:
        import machineid

        raw = (machineid.id() or "").strip()
    except Exception:
        raw = ""

    if not raw:
        import uuid

        raw = f"{uuid.getnode():012x}"

    digest = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest().upper()
    # 分组便于阅读/抄写：XXXX-XXXX-...
    return "-".join(digest[i : i + 4] for i in range(0, 32, 4))


def normalize_machine_code(code: str) -> str:
    """去掉分隔符并转大写，便于比对。"""
    return re.sub(r"[^0-9A-Fa-f]", "", code or "").upper()
