#!/usr/bin/env python3
"""
omni_bot_sdk 开发安装脚本
用于在开发模式下安装 omni_bot_sdk
"""

import os
import sys
import subprocess

def install_dev():
    """开发模式安装"""
    print("🔧 开发模式安装 omni_bot_sdk...")
    
    # 检查当前目录
    if not os.path.exists("pyproject.toml"):
        print("❌ 错误: 请在项目根目录运行此脚本")
        sys.exit(1)
    
    try:
        # 卸载旧版本
        print("🧹 卸载旧版本...")
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "omni-bot-sdk", "-y"], 
                      capture_output=True)
        
        # 开发模式安装
        print("📦 开发模式安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-e", "."])
        
        print("✅ 开发模式安装成功!")
        print("\n📖 说明:")
        print("  - 代码修改会自动生效，无需重新安装")
        print("  - 使用 'pip uninstall omni-bot-sdk' 卸载")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ 安装失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    install_dev()
