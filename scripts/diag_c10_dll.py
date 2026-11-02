"""Find which add_dll_directory target under _internal breaks loading c10.dll."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

INTERNAL = Path(r"d:\project\rpa\omni-bot-sdk-oss-master\dist\omni-bot-win-amd64\_internal")
PKG_LIB = INTERNAL / "torch" / "lib"


def breaks(path: Path) -> bool:
    code = f"""
import ctypes, os
from pathlib import Path
pkg_lib = Path(r"{PKG_LIB}")
os.add_dll_directory(r"{path}")
os.add_dll_directory(str(pkg_lib))
try:
    ctypes.WinDLL(str(pkg_lib / "c10.dll"))
    print("OK")
except OSError:
    print("FAIL")
"""
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    return "FAIL" in out


def main() -> None:
    candidates: list[Path] = []
    candidates.extend(sorted(INTERNAL.glob("*.dll")))
    for d in sorted(x for x in INTERNAL.iterdir() if x.is_dir()):
        if d.name == "torch":
            continue
        if any(d.rglob("*.dll")):
            candidates.append(d)

    print("candidates", len(candidates))
    bad: list[Path] = []
    for c in candidates:
        if breaks(c):
            print("BAD", c.relative_to(INTERNAL))
            bad.append(c)
    print("bad count", len(bad))

    # If a directory is bad, drill into its immediate children
    for b in list(bad):
        if not b.is_dir():
            continue
        print("drill", b.name)
        kids = list(b.glob("*.dll")) + [x for x in b.iterdir() if x.is_dir() and any(x.rglob("*.dll"))]
        for k in kids:
            if breaks(k):
                print("  BAD", k.relative_to(INTERNAL))


if __name__ == "__main__":
    main()
