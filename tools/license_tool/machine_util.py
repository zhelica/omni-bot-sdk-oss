"""独立机器码工具（不依赖 omni_bot_sdk，便于打出小体积 exe）。"""

from __future__ import annotations

import hashlib
import re


def get_machine_code() -> str:
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
    return "-".join(digest[i : i + 4] for i in range(0, 32, 4))


def normalize_machine_code(code: str) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", code or "").upper()
