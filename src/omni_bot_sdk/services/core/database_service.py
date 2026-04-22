"""
database_service 编译扩展模块存根。

该模块为 database_service.cp312-win_amd64.pyd 的导入存根，
通过 PyInstaller 的 binaries 配置将 .pyd 文件打包进 exe。
"""
import importlib.util
import sys
from pathlib import Path

_pyd_path = Path(__file__).with_suffix(".cp312-win_amd64.pyd")

_spec = importlib.util.spec_from_file_location("database_service", _pyd_path)
if _spec and _spec.loader:
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[__name__] = _module
    _spec.loader.exec_module(_module)
else:
    raise ImportError(f"无法加载编译扩展: {_pyd_path}")
