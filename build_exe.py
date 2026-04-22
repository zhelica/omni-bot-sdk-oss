#!/usr/bin/env python3
"""
omni_bot_sdk 桌面应用打包脚本
使用 PyInstaller 将 SDK 打包为独立的 Windows 可执行文件

用法:
    python build_exe.py           # 普通打包
    python build_exe.py --clean    # 清理后重新打包
    python build_exe.py --debug    # 调试模式打包
    python build_exe.py --no-console  # 无控制台窗口版本
"""
import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
SPEC_FILE = PROJECT_ROOT / "omni_bot_sdk.spec"
DIST_DIR = PROJECT_ROOT / "dist"


def run_cmd(cmd: list[str], **kwargs):
    """执行命令并打印输出"""
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, **kwargs)


def check_pyinstaller():
    """确保 PyInstaller 已安装"""
    try:
        import PyInstaller
        print(f"  [OK] PyInstaller {PyInstaller.__version__}")
        return True
    except ImportError:
        print("  [安装] PyInstaller 未安装，正在安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        return True


def ensure_dependencies():
    """确保所有运行时依赖已安装"""
    print("\n[2/5] 检查项目依赖...")
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"
    ])
    # 安装当前项目（确保所有数据文件和 proto 文件可用）
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-e", "."])
    print("  [OK] 依赖就绪")


def check_spec_file():
    """确保 spec 文件存在"""
    if not SPEC_FILE.exists():
        print(f"  [ERROR] {SPEC_FILE} 不存在")
        print("  请先运行 build_lib.py 或手动创建 spec 文件")
        sys.exit(1)
    print(f"  [OK] spec 文件: {SPEC_FILE}")


def clean():
    """清理构建目录"""
    print("\n[1/5] 清理旧构建...")
    dirs = ["build", "dist"]
    for d in dirs:
        p = PROJECT_ROOT / d
        if p.exists():
            shutil.rmtree(p)
            print(f"  [清理] {d}/")
        else:
            print(f"  [跳过] {d}/ (不存在)")
    print("  [OK] 清理完成")


def build(debug: bool = False, no_console: bool = False):
    """执行 PyInstaller 打包"""
    print(f"\n[3/5] 执行打包 (debug={debug}, no_console={no_console})...")

    # 临时修改 spec 文件中的 console 设置
    spec_content = SPEC_FILE.read_text(encoding="utf-8")

    if no_console:
        spec_content = spec_content.replace("console=True", "console=False")
        print("  [模式] 无控制台窗口 (Windows GUI)")

    # 如果是调试模式
    extra_args = []
    if debug:
        extra_args.extend(["--debug=all", "--log-level=DEBUG"])
        print("  [模式] 调试模式")

    cmd = [sys.executable, "-m", "PyInstaller", str(SPEC_FILE), "--clean", *extra_args]
    print(f"  $ {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print("\n  [ERROR] PyInstaller 打包失败!")
        sys.exit(1)

    print("  [OK] 打包完成")


def find_dist_dir() -> Path:
    """查找 dist 目录下生成的目录"""
    if DIST_DIR.exists():
        dirs = [d for d in DIST_DIR.iterdir() if d.is_dir()]
        if dirs:
            return dirs[0]
    return DIST_DIR


def prepare_distribution():
    """准备分发目录"""
    print("\n[4/5] 准备分发目录...")
    dist_app = find_dist_dir()

    if not dist_app.exists():
        print("  [ERROR] dist 目录不存在")
        return

    print(f"  输出目录: {dist_app}")

    # 复制配置文件模板
    example_config = PROJECT_ROOT / "config.example.yaml"
    if example_config.exists():
        target_config = dist_app / "config.yaml"
        if not target_config.exists():
            shutil.copy2(example_config, target_config)
            print(f"  [OK] 已复制配置文件模板 -> {target_config.name}")
    else:
        print("  [提示] 未找到 config.example.yaml，跳过配置文件复制")
        print("  [提示] 请在 exe 同目录下手动创建 config.yaml")

    # 创建启动脚本
    bat_path = dist_app / "启动机器人.bat"
    exe_name = "omni-bot.exe"
    bat_content = f'''@echo off
chcp 65001 >nul
title Omni-Bot
echo ============================================
echo   Omni-Bot 微信RPA机器人
echo ============================================
echo.
echo  正在启动...
echo.

:: 尝试带配置启动
if exist "%~dp0config.yaml" (
    "%~dp0{exe_name}" -c "%~dp0config.yaml"
) else (
    echo [警告] 未找到 config.yaml，将使用默认配置
    "%~dp0{exe_name}"
)

echo.
echo ============================================
echo  程序已退出。按任意键关闭...
pause >nul
'''
    bat_path.write_text(bat_content, encoding="utf-8")
    print(f"  [OK] 已创建启动脚本 -> {bat_path.name}")

    # 复制 README
    readme = PROJECT_ROOT / "README.md"
    if readme.exists():
        shutil.copy2(readme, dist_app / "README.md")
        print(f"  [OK] 已复制 README.md")


def show_result():
    """显示打包结果"""
    print("\n[5/5] 打包结果:")
    dist_app = find_dist_dir()
    if not dist_app.exists():
        print("  [ERROR] dist 目录不存在")
        return

    exe_file = dist_app / "omni-bot.exe"
    if exe_file.exists():
        size_mb = exe_file.stat().st_size / (1024 * 1024)
        print(f"  主程序: {exe_file.name} ({size_mb:.1f} MB)")

    # 统计总大小
    total_size = sum(f.stat().st_size for f in dist_app.rglob("*") if f.is_file())
    total_mb = total_size / (1024 * 1024)
    file_count = sum(1 for f in dist_app.rglob("*") if f.is_file())

    print(f"  总大小: {total_mb:.1f} MB ({file_count} 个文件)")
    print(f"  目录:   {dist_app}")

    print("\n  使用方法:")
    print("    1. 将 config.yaml 放在 exe 同目录")
    print("    2. 运行 启动机器人.bat 或双击 omni-bot.exe")
    print("\n  调试模式:")
    print("    python build_exe.py --debug")


def download_pyinstaller_hooks():
    """下载 PyInstaller 社区 hooks（可选，用于更好的兼容性）"""
    print("\n[提示] 可选: 安装 PyInstaller hooks 以提高兼容性")
    print("  pip install pyinstaller-hooks-contrib")


def main():
    parser = argparse.ArgumentParser(
        description="omni_bot_sdk 桌面应用打包工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--clean", action="store_true", help="打包前清理旧构建")
    parser.add_argument("--debug", action="store_true", help="调试模式打包（显示详细日志）")
    parser.add_argument(
        "--no-console", action="store_true", help="无控制台窗口（纯 Windows GUI 应用）"
    )
    args = parser.parse_args()

    print("=" * 55)
    print("  omni-bot-sdk 桌面应用打包工具")
    print("=" * 55)
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  目录:   {PROJECT_ROOT}")
    print("=" * 55)

    check_pyinstaller()

    if args.clean:
        clean()

    ensure_dependencies()
    check_spec_file()
    build(debug=args.debug, no_console=args.no_console)
    prepare_distribution()
    show_result()

    print("\n[完成] 打包成功!")


if __name__ == "__main__":
    main()
