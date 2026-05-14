# Omni-Bot SDK 桌面应用程序打包指南

本指南介绍如何将 `omni-bot-sdk` 打包为独立的 Windows 桌面可执行文件（`.exe`），无需用户安装 Python 环境即可运行。

---

## 快速开始

### 一键打包（推荐）

```batch
build_exe.bat
```

或使用 Python 脚本：

```bash
python build_exe.py
```

打包完成后，输出目录 `dist/omni-bot-*/` 中即为可直接分发的文件夹。

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `src/omni_bot_sdk/__main__.py` | CLI 入口点，支持 `python -m omni_bot_sdk` 运行 |
| `omni_bot_sdk.spec` | PyInstaller 打包规格文件 |
| `build_exe.py` | Python 打包脚本（跨平台） |
| `build_exe.bat` | Windows 批处理打包脚本（双击即可） |
| `config.example.yaml` | 配置文件模板 |

---

## 详细使用方法

### 基本打包

```bash
# 方式1: 使用批处理（Windows）
build_exe.bat

# 方式2: 使用 Python 脚本
python build_exe.py

# 方式3: 直接调用 PyInstaller
python -m PyInstaller omni_bot_sdk.spec --clean
```

### 清理后重新打包

```bash
python build_exe.py --clean
```

### 调试模式打包

调试模式会显示详细日志，方便排查打包问题：

```bash
python build_exe.py --debug
```

### 无控制台窗口版本

如果不需要显示黑窗口（纯后台服务），可以打包为无控制台版本：

```bash
python build_exe.py --no-console
```

> **注意**: 无控制台版本启动失败时不会有任何错误输出，建议先使用控制台版本调试通过后再切换。

---

## 打包产物

打包成功后，`dist/omni-bot-win-amd64/` 目录包含：

```
dist/omni-bot-win-amd64/
  omni-bot.exe          # 主程序
  python*.dll           # Python 运行时
  *.pyd                 # 扩展模块
  启动机器人.bat         # 一键启动脚本
  config.yaml           # 配置文件（如有模板）
  ...
```

将整个文件夹分发即可，**无需安装 Python 或任何依赖**。

---

## 配置与运行

### 1. 配置

在 exe 同目录下创建或复制 `config.yaml`，参考 `config.example.yaml` 填写：

```yaml
dbkey: your_db_encryption_key_here
mcp:
  host: 0.0.0.0
  port: 8000
# ... 其他配置项
```

### 2. 运行

**方式 A**: 双击 `启动机器人.bat`

**方式 B**: 直接运行 `omni-bot.exe`

**方式 C**: 命令行（可指定配置路径）：

```bash
omni-bot.exe                              # 使用默认 config.yaml
omni-bot.exe -c my_config.yaml           # 使用自定义配置
omni-bot.exe -l DEBUG                    # 调试日志级别
omni-bot.exe -l ERROR                    # 仅错误日志
```

### 3. 常用命令参数

| 参数 | 说明 |
|------|------|
| `-c <path>` | 指定配置文件路径 |
| `-l <LEVEL>` | 设置日志级别 (DEBUG/INFO/WARNING/ERROR) |
| `--version` | 显示版本号 |

---

## 常见问题

### Q1: 打包过程中卡住或报错

**原因**: PyInstaller 对复杂依赖的支持不完善

**解决方案**:

1. 确保所有依赖通过 `pip install -e .` 正确安装
2. 尝试调试模式打包查看具体错误：
   ```bash
   python build_exe.py --debug
   ```
3. 检查 `omni_bot_sdk.spec` 中的 `hiddenimports` 是否完整

### Q2: 运行时提示缺少 DLL 或模块

**解决方案**: 在 spec 文件中添加缺失的包到 `hiddenimports`

```python
hiddenimports += [
    "your_missing_module",
]
```

### Q2b: 源码运行正常，exe 里 `WinError 1114` / `c10.dll` / `onnxruntime_pybind11_state` 加载失败（路径含 `_MEI`）

**原因**: 旧版 **onefile** 单 exe 会把依赖解压到临时目录 `Temp\_MEI*`；PyTorch、ONNX Runtime 等大量原生 DLL 在这种模式下极易初始化失败。

**解决方案**（本仓库已采用）:

1. 使用 **onedir** 输出：`dist/omni-bot-win-amd64/` 目录内含 `omni-bot.exe` 与同目录 DLL，**整目录分发**，不要只拷单个 exe。
2. `omni_bot_sdk.spec` 中已增加 `collect_all("torch")`，与 `ultralytics` / `onnxruntime` 一并收集。
3. 若仍失败：安装 [Microsoft Visual C++ Redistributable](https://learn.microsoft.com/zh-cn/cpp/windows/latest-supported-vc-redist)（x64），并确认杀毒软件未拦截 exe 目录下的 DLL。

### Q2c: exe 里 OCR 一直返回空列表 `[]`、耗时约 0 秒

**常见原因**: 打包环境下 **onnxruntime 仍未加载**，`local_ocr` 为 `None`，且未配置可用的 **远程 OCR**。

**处理方式**:

1. 在 `config.yaml` 的 `rpa.ocr` 中填写可访问的 **`remote_url`**；打包（`sys.frozen`）时若本地未就绪，程序会 **自动尝试远程**（可用 `try_remote_on_local_miss: false` 关闭）。
2. 或设置 **`use_remote: true`** 强制全程走远程。
3. 根本修复仍是 **onedir 打包 + VC++ 运行库**，使本地 RapidOCR 能加载。

### Q3: 打包后体积太大（>500MB）

**正常现象**: omni-bot-sdk 依赖 YOLO (Ultralytics)、ONNX Runtime、Protobuf 等大型库，体积较大是不可避免的。

**可选优化**:

- 使用 UPX 压缩：`upx=True`（需要安装 UPX）
- 使用虚拟环境隔离依赖，只打包必要包

### Q4: Windows Defender 或杀毒软件拦截

**原因**: PyInstaller 打包的 exe 会被部分安全软件误报

**解决方案**:

- 为 exe 添加数字签名
- 提交到杀毒软件厂商白名单
- 使用代码签名证书签名

### Q5: 无控制台版本启动后没有反应

**原因**: 启动失败但没有任何输出

**解决方案**:

1. 先用控制台版本调试：
   ```bash
   python build_exe.py  # 不加 --no-console
   ```
2. 确认正常后，再打包无控制台版本

---

## 进阶：使用 NSIS 创建安装程序

如果需要生成 `.msi` 或 `.exe` 安装包（带安装向导），可以使用 NSIS：

1. 安装 NSIS: https://nsis.sourceforge.io/
2. 编写 NSIS 脚本 `installer.nsi`
3. 使用 `makensis installer.nsi` 生成安装包

示例 NSIS 脚本结构：

```nsis
!include "MUI2.nsh"

Name "Omni-Bot"
OutFile "omni-bot-setup.exe"
InstallDir "$PROGRAMFILES\Omni-Bot"

Section "Install"
    SetOutPath "$INSTDIR"
    File /r "dist\omni-bot-win-amd64\*.*"
    CreateShortcut "$DESKTOP\Omni-Bot.lnk" "$INSTDIR\omni-bot.exe"
SectionEnd
```

---

## 进阶：使用 cx_Freeze（替代 PyInstaller）

cx_Freeze 是 PyInstaller 的替代方案，配置更简洁：

```python
# setup.py
from cx_Freeze import setup, Executable

build_options = {
    "packages": [
        "omni_bot_sdk", "ultralytics", "onnxruntime",
        "rapidocr_onnxruntime", "pyautogui", "pywin32",
    ],
    "excludes": ["tkinter", "matplotlib"],
}

executables = [
    Executable(
        "src/omni_bot_sdk/__main__.py",
        base="Win32GUI" if args.no_console else "Console",
        target_name="omni-bot.exe",
    )
]

setup(
    name="omni-bot",
    version="1.0.0",
    description="Omni-Bot SDK 桌面应用",
    options={"build_exe": build_options},
    executables=executables,
)
```

安装与打包：
```bash
pip install cx_Freeze
python setup.py build
```

---

## 进阶：使用 Nuitka（性能最佳）

Nuitka 将 Python 编译为 C，然后编译为机器码，性能最佳但编译时间较长：

```bash
pip install nuitka

# 编译（带依赖分析）
python -m nuitka ^
    --standalone ^
    --follow-imports ^
    --enable-plugin=pywin32 ^
    --windows-console-mode=attach ^
    --output-filename=omni-bot.exe ^
    --output-dir=dist ^
    src/omni_bot_sdk/__main__.py
```

> Nuitka 编译时间通常 10-30 分钟，但产物体积更小、启动更快。

---

## 架构总览

```
用户需求
    │
    ├─► 快速分发 ──────► PyInstaller (已配置，5-15分钟)
    │
    ├─► 安装向导 ──────► PyInstaller + NSIS
    │
    ├─► 性能最佳 ──────► Nuitka (编译时间长)
    │
    └─► 跨平台 ─────────► PyInstaller + cx_Freeze + 多平台构建

输出格式:
    ├─► 独立 .exe (单文件)
    ├─► 文件夹 (推荐，便于调试)
    ├─► .msi 安装包
    └─► .exe 安装包 (NSIS)
```
