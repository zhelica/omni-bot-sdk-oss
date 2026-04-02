#!/usr/bin/env python3
"""
omni_bot_sdk 打包脚本
用于将 omni_bot_sdk 打包成 Python 库
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

def clean_build_dirs():
    """清理构建目录"""
    print("🧹 清理构建目录...")
    dirs_to_clean = [
        "build",
        "dist", 
        "src/omni_bot_sdk.egg-info",
        "__pycache__",
        "src/omni_bot_sdk/__pycache__"
    ]
    
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"  ✅ 已删除: {dir_name}")

def clean_pyc_files():
    """清理 .pyc 文件"""
    print("🧹 清理 .pyc 文件...")
    for root, dirs, files in os.walk("src"):
        for file in files:
            if file.endswith(".pyc"):
                file_path = os.path.join(root, file)
                os.remove(file_path)
                print(f"  ✅ 已删除: {file_path}")

def check_dependencies():
    """检查依赖是否安装"""
    print("📦 检查构建依赖...")
    required_packages = ["setuptools", "wheel", "build"]
    
    for package in required_packages:
        try:
            __import__(package)
            print(f"  ✅ {package} 已安装")
        except ImportError:
            print(f"  ❌ {package} 未安装，正在安装...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

def build_package():
    """构建包"""
    print("🔨 开始构建包...")
    
    # 使用 build 模块构建
    try:
        subprocess.check_call([sys.executable, "-m", "build"])
        print("  ✅ 构建成功!")
    except subprocess.CalledProcessError as e:
        print(f"  ❌ 构建失败: {e}")
        return False
    
    return True

def show_build_results():
    """显示构建结果"""
    print("\n📋 构建结果:")
    dist_dir = Path("dist")
    if dist_dir.exists():
        for file in dist_dir.iterdir():
            if file.is_file():
                size = file.stat().st_size / (1024 * 1024)  # MB
                print(f"  📦 {file.name} ({size:.2f} MB)")
    else:
        print("  ❌ 未找到构建文件")

def install_locally():
    """本地安装测试"""
    print("\n🧪 本地安装测试...")
    try:
        # 卸载旧版本
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "omni-bot-sdk", "-y"], 
                      capture_output=True)
        
        # 安装新版本
        wheel_file = None
        dist_dir = Path("dist")
        for file in dist_dir.iterdir():
            if file.suffix == ".whl":
                wheel_file = file
                break
        
        if wheel_file:
            subprocess.check_call([sys.executable, "-m", "pip", "install", str(wheel_file)])
            print(f"  ✅ 本地安装成功: {wheel_file.name}")
        else:
            print("  ❌ 未找到 wheel 文件")
            
    except subprocess.CalledProcessError as e:
        print(f"  ❌ 本地安装失败: {e}")

def main():
    """主函数"""
    print("🚀 开始打包 omni_bot_sdk...")
    print("=" * 50)
    
    # 检查当前目录
    if not os.path.exists("pyproject.toml"):
        print("❌ 错误: 请在项目根目录运行此脚本")
        sys.exit(1)
    
    try:
        # 1. 清理构建目录
        clean_build_dirs()
        clean_pyc_files()
        
        # 2. 检查依赖
        check_dependencies()
        
        # 3. 构建包
        if build_package():
            # 4. 显示结果
            show_build_results()
            
            # 5. 询问是否本地安装测试
            response = input("\n❓ 是否进行本地安装测试? (y/n): ").lower().strip()
            if response in ['y', 'yes', '是']:
                install_locally()
        
        print("\n🎉 打包完成!")
        print("\n📖 使用说明:")
        print("  1. 安装: pip install dist/omni-bot-sdk-*.whl")
        print("  2. 上传到 PyPI: python -m twine upload dist/*")
        print("  3. 本地开发: pip install -e .")
        
    except KeyboardInterrupt:
        print("\n⏹️  用户取消操作")
    except Exception as e:
        print(f"\n❌ 打包过程中出现错误: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
