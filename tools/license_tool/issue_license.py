#!/usr/bin/env python
"""签发绑定机器码的本地秘钥（仅发卡方使用）。"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from machine_util import normalize_machine_code


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _load_private_key(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"找不到私钥: {path}")
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def default_private_key_path() -> Path:
    """开发目录或 exe 同目录下的 private_key.pem。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "private_key.pem"
    return Path(__file__).with_name("private_key.pem")


def issue(
    mid: str, expire: str, serial: str = "", private_key_path: Path | None = None
) -> str:
    mid_norm = normalize_machine_code(mid)
    if len(mid_norm) < 16:
        raise ValueError("机器码无效，请确认客户发来的机器码完整")

    try:
        datetime.strptime(expire.strip(), "%Y-%m-%d")
    except ValueError as e:
        raise ValueError("过期日格式须为 YYYY-MM-DD，例如 2026-12-31") from e

    pretty_mid = "-".join(
        mid_norm[i : i + 4] for i in range(0, min(len(mid_norm), 32), 4)
    )
    payload = {
        "mid": pretty_mid,
        "exp": expire.strip(),
        "sn": (serial or uuid.uuid4().hex[:12]).strip(),
        "iat": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    payload_raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )

    key_path = Path(private_key_path) if private_key_path else default_private_key_path()
    private_key = _load_private_key(key_path)
    signature = private_key.sign(payload_raw, padding.PKCS1v15(), hashes.SHA256())
    return f"{_b64url(payload_raw)}.{_b64url(signature)}"


def main():
    parser = argparse.ArgumentParser(description="签发绑定机器码的软件秘钥")
    parser.add_argument("--mid", required=True, help="客户机器码")
    parser.add_argument("--expire", required=True, help="过期日 YYYY-MM-DD")
    parser.add_argument("--sn", default="", help="可选流水号；默认随机")
    parser.add_argument("--key", default="", help="私钥路径")
    args = parser.parse_args()
    try:
        token = issue(
            args.mid,
            args.expire,
            serial=args.sn,
            private_key_path=Path(args.key) if args.key else None,
        )
    except (ValueError, FileNotFoundError) as e:
        raise SystemExit(str(e)) from e
    print(token)


if __name__ == "__main__":
    main()
