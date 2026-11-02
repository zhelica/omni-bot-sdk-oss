"""
PyInstaller runtime hook: 确保 torch 原生 DLL 可加载。

根因：打包进 _internal 的 msvcp140.dll 常与系统 VC 运行库版本不一致，
在 add_dll_directory(_MEIPASS) 后会导致 c10.dll WinError 1114。
此处优先把 torch/lib 加入 DLL 搜索路径，并尽量避开错误的 msvcp140。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _meipass() -> Path | None:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    # onedir 兜底
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "_internal"
    return None


def _setup() -> None:
    base = _meipass()
    if base is None:
        return

    # 冲突的打包版 msvcp140 会导致 c10 初始化失败；优先用系统 VC 运行库
    bad = base / "msvcp140.dll"
    if bad.is_file():
        try:
            bad.unlink()
        except OSError:
            # 删不掉则改名避开搜索
            try:
                bad.rename(base / "msvcp140.dll.bak")
            except OSError:
                pass

    torch_lib = base / "torch" / "lib"
    if torch_lib.is_dir():
        # torch/lib 必须在 PATH 前面，便于依赖解析
        os.environ["PATH"] = str(torch_lib) + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(torch_lib))
            except OSError:
                pass

    # OpenMP 多副本时降低崩溃概率
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("OMP_NUM_THREADS", os.environ.get("OMP_NUM_THREADS", "1"))


_setup()
