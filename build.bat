@echo off
echo 🚀 开始打包 omni_bot_sdk...
echo ================================================

REM 清理构建目录
echo 🧹 清理构建目录...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist src\omni_bot_sdk.egg-info rmdir /s /q src\omni_bot_sdk.egg-info

REM 检查并安装构建依赖
echo 📦 检查构建依赖...
python -m pip install --upgrade setuptools wheel build

REM 构建包
echo 🔨 开始构建包...
python -m build

REM 显示构建结果
echo.
echo 📋 构建结果:
if exist dist (
    for %%f in (dist\*) do (
        echo   📦 %%~nxf
    )
) else (
    echo   ❌ 构建失败
    pause
    exit /b 1
)

echo.
echo 🎉 打包完成!
echo.
echo 📖 使用说明:
echo   1. 安装: pip install dist\omni-bot-sdk-*.whl
echo   2. 上传到 PyPI: python -m twine upload dist\*
echo   3. 本地开发: pip install -e .
echo.
pause
