#!/usr/bin/env python3
"""
omni_bot_sdk 发布脚本
用于将构建好的包发布到 PyPI
"""

import os
import sys
import subprocess
from pathlib import Path

def check_twine():
    """检查 twine 是否安装"""
    try:
        import twine
        print("✅ twine 已安装")
        return True
    except ImportError:
        print("❌ twine 未安装，正在安装...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "twine"])
            print("✅ twine 安装成功")
            return True
        except subprocess.CalledProcessError:
            print("❌ twine 安装失败")
            return False

def check_build_files():
    """检查构建文件是否存在"""
    dist_dir = Path("dist")
    if not dist_dir.exists():
        print("❌ dist 目录不存在，请先运行构建脚本")
        return False
    
    files = list(dist_dir.glob("*.whl")) + list(dist_dir.glob("*.tar.gz"))
    if not files:
        print("❌ 未找到构建文件，请先运行构建脚本")
        return False
    
    print("✅ 找到构建文件:")
    for file in files:
        size = file.stat().st_size / (1024 * 1024)  # MB
        print(f"  📦 {file.name} ({size:.2f} MB)")
    
    return True

def upload_to_pypi(test=False):
    """上传到 PyPI"""
    repository = "testpypi" if test else "pypi"
    repository_url = "https://test.pypi.org/legacy/" if test else "https://upload.pypi.org/legacy/"
    
    print(f"🚀 开始上传到 {repository.upper()}...")
    print(f"   仓库地址: {repository_url}")
    
    try:
        cmd = [sys.executable, "-m", "twine", "upload", "dist/*"]
        if test:
            cmd.extend(["--repository", "testpypi"])
        
        subprocess.check_call(cmd)
        print(f"✅ 上传到 {repository.upper()} 成功!")
        
        if test:
            print("\n📖 测试安装命令:")
            print("   pip install --index-url https://test.pypi.org/simple/ omni-bot-sdk")
        else:
            print("\n📖 安装命令:")
            print("   pip install omni-bot-sdk")
            
    except subprocess.CalledProcessError as e:
        print(f"❌ 上传失败: {e}")
        return False
    
    return True

def main():
    """主函数"""
    print("🚀 omni_bot_sdk 发布工具")
    print("=" * 40)
    
    # 检查当前目录
    if not os.path.exists("pyproject.toml"):
        print("❌ 错误: 请在项目根目录运行此脚本")
        sys.exit(1)
    
    # 检查构建文件
    if not check_build_files():
        sys.exit(1)
    
    # 检查 twine
    if not check_twine():
        sys.exit(1)
    
    # 选择发布目标
    print("\n📋 选择发布目标:")
    print("  1. 测试 PyPI (testpypi.org)")
    print("  2. 正式 PyPI (pypi.org)")
    print("  3. 取消")
    
    while True:
        choice = input("\n请选择 (1-3): ").strip()
        if choice == "1":
            upload_to_pypi(test=True)
            break
        elif choice == "2":
            # 确认发布到正式 PyPI
            confirm = input("⚠️  确认发布到正式 PyPI? 这将影响所有用户 (y/n): ").lower().strip()
            if confirm in ['y', 'yes', '是']:
                upload_to_pypi(test=False)
            else:
                print("❌ 已取消发布")
            break
        elif choice == "3":
            print("❌ 已取消发布")
            break
        else:
            print("❌ 无效选择，请输入 1-3")

if __name__ == "__main__":
    main()
