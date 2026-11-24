"""本地验签：校验机器码绑定与过期日。"""

from __future__ import annotations

import base64
import json
import sys
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from omni_bot_sdk.licensing.machine import get_machine_code, normalize_machine_code

# 内嵌公钥，避免 PyInstaller 漏打 public_key.pem 导致验签失败
_EMBEDDED_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAibjRCUlDnp8WmzwLUbnM
BzWtYSSlhrYgRjbjr5/MP9DyKVFooKUpGYXZVWrPn52hNRb23MXtA5QDYM34FPPz
6yILA7Z62TzKnQjfw6MHSOd2DG//1a1UeyhF6LizVOgB2+/osjK0Rn2iHRGW35rS
v7rn0exUay0c94J3XQtNVQF39hSLSJ5FwBtQQuko+gAk8M0KQuee648V7MZOPnKN
iPO169CjzA5Hrip0LuwAtkH77DhMbblCmeUJkEG1O5E6ZABtzHCVOKzgxdYwWk4T
RvyayYa1rhYcrIWfbPN8OSmo7FEFZu2cQmD52ojLA6ehP8YjCfw0y6/HP4gNybjN
nQIDAQAB
-----END PUBLIC KEY-----
"""


class LicenseError(Exception):
    """秘钥校验失败。"""

    def __init__(self, message: str, *, code: str = "invalid"):
        super().__init__(message)
        self.code = code  # invalid | machine | expired | empty


@dataclass
class LicenseInfo:
    machine_code: str
    expires_date: str  # YYYY-MM-DD
    serial: str
    raw: Dict[str, Any]


def _candidate_public_key_paths() -> list[Path]:
    paths: list[Path] = [Path(__file__).with_name("public_key.pem")]
    # PyInstaller onedir / onefile
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
        paths.extend(
            [
                base / "omni_bot_sdk" / "licensing" / "public_key.pem",
                base / "licensing" / "public_key.pem",
                base / "public_key.pem",
            ]
        )
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        paths.extend(
            [
                exe_dir / "omni_bot_sdk" / "licensing" / "public_key.pem",
                exe_dir / "_internal" / "omni_bot_sdk" / "licensing" / "public_key.pem",
                exe_dir / "public_key.pem",
            ]
        )
    return paths


def _load_public_key():
    for pem_path in _candidate_public_key_paths():
        try:
            if pem_path.exists():
                return serialization.load_pem_public_key(pem_path.read_bytes())
        except Exception:
            continue
    # 打包漏文件时回退内嵌公钥
    try:
        return serialization.load_pem_public_key(_EMBEDDED_PUBLIC_KEY_PEM)
    except Exception as e:
        raise LicenseError("缺少本地公钥文件", code="invalid") from e


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + pad).encode("ascii"))


def _parse_license_token(token: str) -> Dict[str, Any]:
    """
    秘钥格式：base64url(payload_json).base64url(signature)
    payload 字段：mid, exp(YYYY-MM-DD), sn
    """
    token = (token or "").strip().replace("\n", "").replace(" ", "")
    if not token or "." not in token:
        raise LicenseError("秘钥格式无效", code="invalid")
    parts = token.split(".")
    if len(parts) != 2:
        raise LicenseError("秘钥格式无效", code="invalid")
    payload_b64, sig_b64 = parts
    try:
        payload_raw = _b64url_decode(payload_b64)
        signature = _b64url_decode(sig_b64)
        payload = json.loads(payload_raw.decode("utf-8"))
    except Exception as e:
        raise LicenseError(f"秘钥解析失败: {e}", code="invalid") from e

    public_key = _load_public_key()
    try:
        public_key.verify(
            signature,
            payload_raw,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except Exception as e:
        raise LicenseError("秘钥验签失败", code="invalid") from e

    if not isinstance(payload, dict):
        raise LicenseError("秘钥内容无效", code="invalid")
    return payload


def _parse_expires_end(exp: str) -> datetime:
    exp = (exp or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            dt = datetime.strptime(exp, fmt)
            if fmt in ("%Y-%m-%d", "%Y/%m/%d"):
                return datetime.combine(dt.date(), time(23, 59, 59))
            return dt
        except ValueError:
            continue
    raise LicenseError(f"过期日期无效: {exp}", code="invalid")


def verify_license(
    key: str,
    *,
    machine_code: Optional[str] = None,
    now: Optional[datetime] = None,
) -> LicenseInfo:
    """
    校验本地秘钥。
    - 验签
    - 机器码必须与本机一致
    - 过期日（填到某天，当天 23:59:59 前有效）
    """
    if not (key or "").strip():
        raise LicenseError("秘钥未配置", code="empty")

    payload = _parse_license_token(key)
    mid = str(payload.get("mid") or "").strip()
    exp = str(payload.get("exp") or "").strip()
    sn = str(payload.get("sn") or "").strip()
    if not mid or not exp:
        raise LicenseError("秘钥缺少机器码或过期日", code="invalid")

    local_mid = normalize_machine_code(machine_code or get_machine_code())
    license_mid = normalize_machine_code(mid)
    if not local_mid or local_mid != license_mid:
        raise LicenseError("秘钥与当前机器不匹配", code="machine")

    expires_at = _parse_expires_end(exp)
    current = now or datetime.now()
    if current > expires_at:
        raise LicenseError(f"秘钥已过期，过期时间: {exp}", code="expired")

    return LicenseInfo(
        machine_code=mid,
        expires_date=exp,
        serial=sn,
        raw=payload,
    )
