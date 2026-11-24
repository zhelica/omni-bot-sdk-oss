#!/usr/bin/env python
"""打印本机机器码（客户报码 / 自测用）。"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from machine_util import get_machine_code


def main():
    code = get_machine_code()
    print(code)
    print("请将以上机器码发送给发卡方，用于绑定秘钥。", file=sys.stderr)


if __name__ == "__main__":
    main()
