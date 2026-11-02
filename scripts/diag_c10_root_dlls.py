"""Find which _internal root DLLs break c10 when exposed together via add_dll_directory."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

INTERNAL = Path(r"d:\project\rpa\omni-bot-sdk-oss-master\dist\omni-bot-win-amd64\_internal")
PKG_LIB = INTERNAL / "torch" / "lib"
ROOT_DLLS = sorted(INTERNAL.glob("*.dll"))


def breaks_with_dlls(dll_files: list[Path]) -> bool:
    with tempfile.TemporaryDirectory(prefix="c10probe_") as td:
        td_path = Path(td)
        for dll in dll_files:
            os.link(dll, td_path / dll.name) if False else shutil.copy2(dll, td_path / dll.name)
        code = f"""
import ctypes, os
from pathlib import Path
pkg_lib = Path(r"{PKG_LIB}")
os.add_dll_directory(r"{td_path}")
os.add_dll_directory(str(pkg_lib))
try:
    ctypes.WinDLL(str(pkg_lib / "c10.dll"))
    print("OK")
except OSError:
    print("FAIL")
"""
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        return "FAIL" in ((r.stdout or "") + (r.stderr or ""))


def main() -> None:
    print("root dlls", len(ROOT_DLLS))
    if not breaks_with_dlls(ROOT_DLLS):
        print("all root dlls together: OK (unexpected)")
        return
    print("all root dlls together: FAIL (expected)")

    # binary search
    bad = list(ROOT_DLLS)
    while len(bad) > 1:
        mid = len(bad) // 2
        left, right = bad[:mid], bad[mid:]
        if breaks_with_dlls(left):
            bad = left
            print("narrow left", len(bad), bad[0].name if bad else "")
        elif breaks_with_dlls(right):
            bad = right
            print("narrow right", len(bad), bad[0].name if bad else "")
        else:
            # interaction between halves — test singles
            print("interaction; testing singles in set", len(bad))
            singles = [d for d in bad if breaks_with_dlls([d])]
            if singles:
                bad = singles
                break
            # try pairs
            found = None
            for i, a in enumerate(bad):
                for b in bad[i + 1 :]:
                    if breaks_with_dlls([a, b]):
                        found = [a, b]
                        break
                if found:
                    break
            bad = found or bad[:1]
            break

    print("BAD set:")
    for d in bad:
        print(" ", d.name)


if __name__ == "__main__":
    main()
