# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置文件
打包命令:
    # 开发/调试打包
    pyinstaller omni_bot_sdk.spec --clean --debug=all

    # 生产打包
    pyinstaller omni_bot_sdk.spec --clean
    # 或使用 build.bat:
    build_exe.bat

输出目录: dist/omni-bot-win-amd64/
"""
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules
try:
    _spec_file = __file__
except NameError:
    _spec_file = sys.argv[0] if sys.argv else "omni_bot_sdk.spec"

project_root = Path(_spec_file).resolve().parent
src_dir = project_root / "src"

block_cipher = None

# ============== 动态收集依赖 ==============

# 收集 yara 模块
yara_datas, yara_binaries, yara_hiddenimports = collect_all("yara")
hiddenimports = list(yara_hiddenimports)

# 收集 protobuf
protobuf_datas, protobuf_binaries, protobuf_hiddenimports = collect_all("google.protobuf")
hiddenimports += list(protobuf_hiddenimports)

# 收集 ultralytics (YOLO)
ultralytics_datas, ultralytics_binaries, ultralytics_hiddenimports = collect_all("ultralytics")
hiddenimports += list(ultralytics_hiddenimports)

# 收集 rapidocr (注意: 需收集 rapidocr 而非 rapidocr_onnxruntime stub)
rapidocr_datas, rapidocr_binaries, rapidocr_hiddenimports = collect_all("rapidocr")
hiddenimports += list(rapidocr_hiddenimports)

# 收集 omegaconf (rapidocr 依赖)
omegaconf_datas, omegaconf_binaries, omegaconf_hiddenimports = collect_all("omegaconf")
hiddenimports += list(omegaconf_hiddenimports)

# 收集 minio
minio_datas, minio_binaries, minio_hiddenimports = collect_all("minio")
hiddenimports += list(minio_hiddenimports)

# 收集 pymem
pymem_datas, pymem_binaries, pymem_hiddenimports = collect_all("pymem")
hiddenimports += list(pymem_hiddenimports)

# 收集 sqlcipher
sqlcipher_datas, sqlcipher_binaries, sqlcipher_hiddenimports = collect_all("sqlcipher3")
hiddenimports += list(sqlcipher_hiddenimports)

# 收集 fastmcp
fastmcp_datas, fastmcp_binaries, fastmcp_hiddenimports = collect_all("fastmcp")
hiddenimports += list(fastmcp_hiddenimports)

# 收集 mcp (fastmcp 依赖)
mcp_datas, mcp_binaries, mcp_hiddenimports = collect_all("mcp")
hiddenimports += list(mcp_hiddenimports)

# 收集 cryptography
cryptography_datas, cryptography_binaries, cryptography_hiddenimports = collect_all("cryptography")
hiddenimports += list(cryptography_hiddenimports)

# 收集 pycryptodome (fuck_zxl.pyd 依赖 Crypto.Util.Padding)
pycryptodome_datas, pycryptodome_binaries, pycryptodome_hiddenimports = collect_all("Crypto")
hiddenimports += list(pycryptodome_hiddenimports)

# 收集 boto3
boto3_datas, boto3_binaries, boto3_hiddenimports = collect_all("boto3")
hiddenimports += list(boto3_hiddenimports)

# 收集 lxml
lxml_datas, lxml_binaries, lxml_hiddenimports = collect_all("lxml")
hiddenimports += list(lxml_hiddenimports)

# 收集 yaml
yaml_datas, yaml_binaries, yaml_hiddenimports = collect_all("ruamel.yaml")
hiddenimports += list(yaml_hiddenimports)

# 收集 colorlog (logging 依赖)
colorlog_datas, colorlog_binaries, colorlog_hiddenimports = collect_all("colorlog")
hiddenimports += list(colorlog_hiddenimports)

# 收集 mss (屏幕截图)
mss_datas, mss_binaries, mss_hiddenimports = collect_all("mss")
hiddenimports += list(mss_hiddenimports)

# 收集 fuzzywuzzy (模糊匹配)
fuzzywuzzy_datas, fuzzywuzzy_binaries, fuzzywuzzy_hiddenimports = collect_all("fuzzywuzzy")
hiddenimports += list(fuzzywuzzy_hiddenimports)

# 收集 python-Levenshtein (fuzzywuzzy 依赖)
python_levenshtein_datas, python_levenshtein_binaries, python_levenshtein_hiddenimports = collect_all("Levenshtein")
hiddenimports += list(python_levenshtein_hiddenimports)

# 收集 watchfiles (文件监控)
watchfiles_datas, watchfiles_binaries, watchfiles_hiddenimports = collect_all("watchfiles")
hiddenimports += list(watchfiles_hiddenimports)

# 收集 requests (HTTP 客户端)
requests_datas, requests_binaries, requests_hiddenimports = collect_all("requests")
hiddenimports += list(requests_hiddenimports)

# 收集 imagehash (图像哈希)
imagehash_datas, imagehash_binaries, imagehash_hiddenimports = collect_all("imagehash")
hiddenimports += list(imagehash_hiddenimports)

# ============== 核心 hidden imports ==============
hiddenimports += [
    #Protobuf runtime
    "google._upb._message",
    "google.protobuf.internal",
    "google.protobuf.internal.containers",
    "google.protobuf.internal.enum_type_wrapper",
    "google.protobuf.internal.message_listener",
    "google.protobuf.pyext",
    "google.protobuf.pyext.cpp_message",
    # Sqlcipher3
    "sqlcipher3",
    "sqlcipher3.sqlite3",
    # YARA
    "yara",
    "yara.rules",
    # MCP
    "mcp.server.fastmcp",
    "mcp.types",
    "mcp.server",
    # FastMCP
    "fastmcp.server",
    "fastmcp.client",
    # RPA / Windows
    "win32api",
    "win32con",
    "win32gui",
    "win32gui_struct",
    "win32print",
    "win32process",
    "win32service",
    "win32timezone",
    "pywintypes",
    # rapidocr
    "rapidocr",
    "omegaconf",
    "omegaconf.omegaconf",
    "onnx",
    "rapidocr.inference_engine.torch",
    "rapidocr.networks",
    # pyautogui
    "pyautogui",
    # image hash
    "imagehash",
    "PIL",
    "PIL.Image",
    "cv2",
    "numpy",
    # MQTT
    "paho.mqtt.client",
    # async
    "asyncio",
    "aiohttp",
    "aiofiles",
    # zstandard
    "zstandard",
    # pyjwt
    "jwt",
    "jwt.algorithms",
    # openai
    "openai",
    "openai._base_types",
    # pydantic
    "pydantic",
    "pydantic.fields",
    "pydantic.main",
    "pydantic.annotated_handlers",
    "pydantic.functional_validators",
    "pydantic.functional_serializers",
    "pydantic.type_adapter",
    "pydantic_core",
    "pydantic_core._pydantic_core",
    # pymachineid
    "py_machine_id",
    # msgraph
    "msgraph",
    "kiota_authentication_azure",
    "kiota_http",
    "kiota_serialization_json",
    "kiota_serialization_text",
    "kiota_serialization_form",
    "kiota_serialization_multipart",
    # uvicorn
    "uvicorn",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # starlette
    "starlette",
    "starlette.routing",
    "starlette.middleware",
    "starlette.middleware.cors",
    "starlette.middleware.base",
    "starlette.responses",
    "starlette.requests",
    "starlette.status",
    "starlette.types",
    # httpx
    "httpx",
    # websockets
    "websockets",
    # entry points
    "pkg_resources",
    "pkg_resources.extern",
    "importlib_metadata",
    "importlib_metadata._adapters",
    "importlib_metadata._functools",
    # aiohttp
    "aiohttp._http_writer",
    "aiohttp._http_parser",
    "aiohttp.base_protocol",
    "aiohttp.client_proto",
    "aiohttp.client_reqrep",
    "aiohttp.hdrs",
    "aiohttp.helpers",
    "aiohttp.http",
    "aiohttp.http_exceptions",
    "aiohttp.http_parser",
    "aiohttp.http_websocket_writer",
    "aiohttp.http_websocket_reader",
    "aiohttp.streams",
    "aiohttp.connector",
    "aiohttp.client",
    "aiohttp.client_fingerprint",
    "aiohttp.locks",
    "aiohttp.multipart",
    "aiohttp.payload",
    "aiohttp.proxy",
    "aiohttp.server",
    "aiohttp.signals",
    "aiohttp.tracing",
    "aiohttp.typedefs",
    "aiohttp.web_exceptions",
    "aiohttp.web_log",
    "aiohttp.web_middlewares",
    "aiohttp.web_protocol",
    "aiohttp.web_request",
    "aiohttp.web_response",
    "aiohttp.web_server",
    "aiohttp.web_urldispatcher",
    "aiohttp.web_ws",
    "aiohttp.worker_srv",
    "aiohttp_sse",
    "yarl",
    "multidict",
    "frozenlist",
    "aiosignal",
    "attr",
    "attrs",
    # minio
    "urllib3",
    "certifi",
    # paho-mqtt
    "paho.mqtt",
    # aiofiles
    "aiofiles",
    # openai
    "tiktoken",
    "tiktoken_ext",
    "tiktoken_ext.openai_public",
    # boto3
    "botocore",
    "botocore.auth",
    "botocore.compat",
    "botocore.config",
    "botocore.exceptions",
    "botocore.hooks",
    "botocore.loaders",
    "botocore.model",
    "botocore.paginate",
    "botocore.params",
    "botocore.retryhandler",
    "botocore.serialize",
    "botocore.session",
    "botocore.utils",
    "botocore.waiter",
    # requests / httpx
    "requests",
    "requests.api",
    "requests.auth",
    "requests.models",
    "requests.sessions",
    "requests.utils",
    "requests.packages",
    "charset_normalizer",
    "idna",
    "urllib3.util",
    "urllib3.util.retry",
    "urllib3.util.url",
    "urllib3.response",
    "certifi",
    # win32 COM
    "win32com",
    "win32com.client",
    "win32com.client.gencache",
    "win32com.shell",
    "win32com.shell.shellcon",
    "pythoncom",
    "pywintypes",
    # importlib
    "importlib.util",
    "importlib.resources",
    "importlib.resources.abc",
    "importlib.abc",
    # Levenshtein
    "Levenshtein",
    # xmltodict
    "xmltodict",
    # python-Levenshtein
    "rapidfuzz",
    "rapidfuzz.distance",
    "rapidfuzz.fuzz",
    # utils
    # "omni_bot_sdk.utils.fuck_zxl",
]

# ============== 数据文件收集 ==============

# egg-info 和 yolo 模型由 build_exe.bat 手动复制，此处保留空定义供 datas 合并使用
egg_info_datas = []
yolo_datas = []

# protobuf .proto 文件 (相对于 project_root)
proto_datas = []
proto_src = project_root / "src" / "omni_bot_sdk" / "weixin" / "parser" / "util" / "protocbuf"
if proto_src.exists():
    proto_datas = [
        (str(proto_src), "omni_bot_sdk/weixin/parser/util/protocbuf"),
    ]

# ============== 合并所有数据文件 ==============

datas = (
    proto_datas
    + egg_info_datas
    + yolo_datas
    + yara_datas
    + protobuf_datas
    + ultralytics_datas
    + rapidocr_datas
    + omegaconf_datas
    + minio_datas
    + pymem_datas
    + sqlcipher_datas
    + fastmcp_datas
    + mcp_datas
    + cryptography_datas
    + pycryptodome_datas
    + boto3_datas
    + lxml_datas
    + yaml_datas
    + colorlog_datas
    + mss_datas
    + fuzzywuzzy_datas
    + python_levenshtein_datas
    + watchfiles_datas
    + requests_datas
    + imagehash_datas
)

# ============== 二进制文件 ==============

binaries = (
    yara_binaries
    + protobuf_binaries
    + ultralytics_binaries
    + rapidocr_binaries
    + omegaconf_binaries
    + minio_binaries
    + pymem_binaries
    + sqlcipher_binaries
    + fastmcp_binaries
    + mcp_binaries
    + cryptography_binaries
    + pycryptodome_binaries
    + boto3_binaries
    + lxml_binaries
    + yaml_binaries
    + colorlog_binaries
    + mss_binaries
    + fuzzywuzzy_binaries
    + python_levenshtein_binaries
    + watchfiles_binaries
    + requests_binaries
    + imagehash_binaries
    # fuck_zxl.pyd 编译扩展
    + [(str(project_root / "src" / "omni_bot_sdk" / "utils" / "fuck_zxl.cp312-win_amd64.pyd"),
        "omni_bot_sdk/utils"),
       (str(project_root / "src" / "omni_bot_sdk" / "services" / "core" / "database_service.cp312-win_amd64.pyd"),
        "omni_bot_sdk/services/core")]
)

# ============== SPEC 核心配置 ==============

a = Analysis(
    [str(src_dir / "omni_bot_sdk" / "__main__.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(project_root / "src" / "omni_bot_sdk" / "_pyinstaller")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "notebook",
        "IPython",
        "jupyter",
        "test",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="omni-bot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,           # 设为 False 可隐藏控制台窗口 (仅 Windows GUI App)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
