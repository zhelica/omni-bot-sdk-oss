"""生成考公题库 jsonl 与答案 JSON。运行: python scripts/generate_civil_service_bank.py"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src" / "omni_bot_sdk" / "plugins" / "core"
RAW = CORE / "civil_service_questions_raw.txt"

_INLINE = re.compile(r"([A-D])\.\s*(.+?)(?=\s+[A-D]\.|$)")
_OPT = re.compile(r"^([A-D])\.\s*(.+)$")
_Q = re.compile(r"^(\d+)\.\s*(.+)$")
_SEC = re.compile(r"^[一二三四五六]、")

def _parse_options(line: str) -> dict[str, str]:
    opts = {k: v.strip() for k, v in _INLINE.findall(line)}
    if opts:
        return opts
    m = _OPT.match(line.strip())
    if m:
        return {m.group(1): m.group(2).strip()}
    return {}


def parse_raw(text: str) -> list[dict]:
    section = ""
    current: dict | None = None
    rows: list[dict] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _SEC.match(line):
            section = line
            continue
        m_q = _Q.match(line)
        if m_q:
            if current:
                rows.append(current)
            num = int(m_q.group(1))
            stem = m_q.group(2).strip()
            current = {
                "number": num,
                "section": section,
                "stem": stem,
                "options": {},
            }
            opts = _parse_options(line)
            if opts:
                current["options"] = opts
            continue
        if current is None:
            continue
        opts = _parse_options(line)
        if opts:
            current["options"].update(opts)
            continue
        m_o = _OPT.match(line)
        if m_o:
            current["options"][m_o.group(1)] = m_o.group(2).strip()

    if current:
        rows.append(current)
    return rows


def main() -> int:
    if not RAW.exists():
        print(f"缺少题库原文: {RAW}", file=sys.stderr)
        return 1
    text = RAW.read_text(encoding="utf-8")
    rows = parse_raw(text)
    if len(rows) != 100:
        print(f"解析到 {len(rows)} 题，期望 100", file=sys.stderr)
        nums = [r["number"] for r in rows]
        print(f"题号范围: {min(nums) if nums else '?'}-{max(nums) if nums else '?'}", file=sys.stderr)
        return 1

    jsonl_path = CORE / "civil_service_questions.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"已写入 {jsonl_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
