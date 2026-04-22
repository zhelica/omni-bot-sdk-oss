@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul

echo.
echo  ================================================
echo   omni-bot-sdk 桌面应用程序打包脚本
echo  ================================================
echo.

REM ---------- 检查 Python ----------
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 Python，请先安装 Python 3.12+
    pause
    exit /b 1
)

REM ---------- 检查 PyInstaller ----------
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [INFO] PyInstaller 未安装，正在安装...
    python -m pip install pyinstaller -q
    if errorlevel 1 (
        echo [ERROR] PyInstaller 安装失败
        pause
        exit /b 1
    )
)

REM ---------- 清理旧构建 ----------
echo [清理] 移除旧构建文件...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

REM ---------- 预安装所有依赖 ----------
echo.
echo [INFO] 确保所有依赖已安装...
python -m pip install --upgrade pip setuptools wheel -q
python -m pip install -e . -q

REM ---------- 预检查 .spec 文件 ----------
if not exist "omni_bot_sdk.spec" (
    echo [ERROR] omni_bot_sdk.spec 不存在
    pause
    exit /b 1
)

REM ---------- 执行打包 ----------
echo.
echo [打包] 开始 PyInstaller 打包...
echo [提示] 打包过程可能需要 5-15 分钟，请耐心等待...
echo.

python -m PyInstaller omni_bot_sdk.spec --clean

if errorlevel 1 (
    echo.
    echo [ERROR] 打包失败，请检查上方错误信息
    pause
    exit /b 1
)

REM ---------- 查找 dist 目录 ----------
echo.
echo [整理] 准备分发目录...

REM 优先使用 omni-bot-win-amd64，否则取 dist 下的第一个子目录
if exist "dist\omni-bot-win-amd64" (
    set "DIST_DIR=dist\omni-bot-win-amd64"
) else (
    for /d %%d in ("dist\*") do (
        set "DIST_DIR=%%d"
        goto :found_dist
    )
    set "DIST_DIR=dist"
)
:found_dist

echo [分发目录] %DIST_DIR%

REM ---------- 手动复制 msg_rec.pt ----------
set "MODEL_SRC=src\omni_bot_sdk\yolo\models\msg_rec.pt"
if exist "%MODEL_SRC%" (
    copy /y "%MODEL_SRC%" "%DIST_DIR%\msg_rec.pt" >nul
    if errorlevel 1 (
        echo [WARN] 复制 msg_rec.pt 失败，请手动复制到 exe 同目录
    ) else (
        echo [OK] msg_rec.pt 已复制到 %DIST_DIR%
    )
) else (
    echo [WARN] 未找到 %MODEL_SRC%，请手动复制到 exe 同目录
)

REM ---------- 手动复制 omni_bot_sdk.egg-info ----------
set "EGGINFO_SRC=src\omni_bot_sdk.egg-info"
if exist "%EGGINFO_SRC%" (
    if not exist "%DIST_DIR%\omni_bot_sdk.egg-info" mkdir "%DIST_DIR%\omni_bot_sdk.egg-info"
    copy /y "%EGGINFO_SRC%\*" "%DIST_DIR%\omni_bot_sdk.egg-info\" >nul
    if errorlevel 1 (
        echo [WARN] 复制 omni_bot_sdk.egg-info 失败
    ) else (
        echo [OK] omni_bot_sdk.egg-info 已复制到 %DIST_DIR%
    )
) else (
    echo [WARN] 未找到 %EGGINFO_SRC%，插件入口点可能失效
)

REM ---------- 复制配置文件模板 ----------
if exist "config.example.yaml" (
    copy /y "config.example.yaml" "%DIST_DIR%\config.yaml" >nul
    echo [OK] config.yaml 模板已复制
) else (
    echo [提示] 未找到 config.example.yaml，跳过
)

REM ---------- 复制 README ----------
if exist "README.md" (
    copy /y "README.md" "%DIST_DIR%\README.md" >nul
)

REM ---------- 创建启动脚本 ----------
echo @echo off > "%DIST_DIR%\启动机器人.bat"
echo title Omni-Bot >> "%DIST_DIR%\启动机器人.bat"
echo echo 正在启动 Omni-Bot... >> "%DIST_DIR%\启动机器人.bat"
echo echo. >> "%DIST_DIR%\启动机器人.bat"
echo "%%~dp0omni-bot.exe" -c "%%~dp0config.yaml" >> "%DIST_DIR%\启动机器人.bat"
echo if errorlevel 1 pause >> "%DIST_DIR%\启动机器人.bat"

REM ---------- 显示结果 ----------
echo.
echo  ================================================
echo   打包完成!
echo  ================================================
echo.
echo  输出目录: %DIST_DIR%
echo.
echo  验证打包结果:
if exist "%DIST_DIR%\msg_rec.pt" (
    echo  [OK] msg_rec.pt
) else (
    echo  [X]  msg_rec.pt 缺失!
)
if exist "%DIST_DIR%\omni_bot_sdk.egg-info\entry_points.txt" (
    echo  [OK] omni_bot_sdk.egg-info\entry_points.txt
) else (
    echo  [X]  omni_bot_sdk.egg-info\entry_points.txt 缺失!
)
echo.
pause
