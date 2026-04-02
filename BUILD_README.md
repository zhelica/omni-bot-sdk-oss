# omni_bot_sdk 打包和发布指南

本指南说明如何将 `omni_bot_sdk` 打包成 Python 库并发布。

## 📦 打包方式

### 方式一：使用 Python 脚本（推荐）

```bash
# 打包
python build_lib.py

# 发布到测试 PyPI
python publish.py

# 开发模式安装
python install_dev.py
```

### 方式二：使用批处理脚本（Windows）

```cmd
# 打包
build.bat
```

### 方式三：使用命令行

```bash
# 安装构建工具
pip install build twine

# 清理旧文件
rm -rf build dist src/omni_bot_sdk.egg-info

# 构建包
python -m build

# 发布到测试 PyPI
python -m twine upload --repository testpypi dist/*

# 发布到正式 PyPI
python -m twine upload dist/*
```

## 🔧 开发模式安装

开发模式安装允许你修改代码后无需重新安装：

```bash
# 开发模式安装
pip install -e .

# 或者使用脚本
python install_dev.py
```

## 📋 构建产物

构建完成后，`dist/` 目录会包含：

- `omni-bot-sdk-2.0.0-py3-none-any.whl` - Wheel 包（推荐）
- `omni-bot-sdk-2.0.0.tar.gz` - 源码包

## 🚀 发布流程

### 1. 测试发布

```bash
# 发布到测试 PyPI
python -m twine upload --repository testpypi dist/*

# 测试安装
pip install --index-url https://test.pypi.org/simple/ omni-bot-sdk
```

### 2. 正式发布

```bash
# 发布到正式 PyPI
python -m twine upload dist/*

# 安装
pip install omni-bot-sdk
```

## 📁 项目结构

```
omni-bot-sdk-oss-master/
├── src/
│   └── omni_bot_sdk/          # 主包目录
├── pyproject.toml             # 项目配置
├── MANIFEST.in                # 包含文件配置
├── build_lib.py               # 打包脚本
├── build.bat                  # Windows 打包脚本
├── publish.py                 # 发布脚本
├── install_dev.py             # 开发安装脚本
└── BUILD_README.md            # 本文件
```

## ⚙️ 配置说明

### pyproject.toml 关键配置

```toml
[project]
name = "omni-bot-sdk"
version = "2.0.0"
dependencies = [
    # 依赖列表
]

[project.entry-points."omni_bot.plugins"]
# 插件入口点配置
self-msg-plugin = "omni_bot_sdk.plugins.core.self_msg_plugin:SelfMsgPlugin"
```

### MANIFEST.in 配置

```
global-include *.py
recursive-include src/omni_bot_sdk/yolo/models *.pt
recursive-include src/omni_bot_sdk *.pyd
include config.example.yaml
```

## 🐛 常见问题

### 1. 构建失败

- 检查 Python 版本 >= 3.12
- 确保所有依赖已安装
- 清理 `__pycache__` 目录

### 2. 发布失败

- 检查 PyPI 账户权限
- 确保版本号唯一
- 检查网络连接

### 3. 导入错误

- 确保包已正确安装
- 检查 Python 路径
- 验证包结构

## 📚 相关命令

```bash
# 查看包信息
pip show omni-bot-sdk

# 查看已安装的包
pip list | grep omni

# 卸载包
pip uninstall omni-bot-sdk

# 查看包内容
pip show -f omni-bot-sdk
```

## 🔗 相关链接

- [Python 打包指南](https://packaging.python.org/)
- [setuptools 文档](https://setuptools.pypa.io/)
- [PyPI 发布指南](https://packaging.python.org/tutorials/packaging-projects/)
