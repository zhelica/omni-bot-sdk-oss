#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
omni_bot_sdk CLI 入口点
支持以下运行方式:
    python -m omni_bot_sdk
    omni-bot
"""
import argparse
import logging
import sys
import os
from pathlib import Path

from omni_bot_sdk.bot import Bot


def parse_args():
    parser = argparse.ArgumentParser(
        prog="omni-bot",
        description="Omni-Bot SDK - 微信RPA机器人运行时",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  omni-bot                          # 使用默认 config.yaml 启动
  omni-bot -c my_config.yaml        # 使用自定义配置文件
  omni-bot -l DEBUG                 # 设置日志级别
  omni-bot --version                # 显示版本
        """,
    )
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        dest="config_path",
        help="配置文件路径 (默认: config.yaml)",
    )
    parser.add_argument(
        "-l", "--log-level",
        default="INFO",
        dest="log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="日志级别 (默认: INFO)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="omni-bot-sdk 1.0.0",
        help="显示版本信息",
    )
    return parser.parse_args()


def configure_logging(level: str):
    import importlib
    spec = importlib.util.find_spec("omni_bot_sdk.utils.logging_setup")
    if spec:
        from omni_bot_sdk.utils.logging_setup import setup_logging
        numeric_level = getattr(logging, level.upper(), logging.INFO)
        setup_logging(log_dir="logs", log_level=numeric_level)
    else:
        logging.basicConfig(
            level=getattr(logging, level.upper(), logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )


def find_config():
    """从多个可能的位置查找配置文件"""
    candidates = [
        Path("config.yaml"),
        Path("config.yml"),
        Path("omni_bot_sdk", "config.yaml"),
        Path("omni_bot_sdk", "config.yml"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def main():
    args = parse_args()

    # 如果指定了配置文件，优先使用
    if args.config_path:
        config_path = args.config_path
        if not os.path.exists(config_path):
            print(f"[ERROR] 配置文件不存在: {config_path}", file=sys.stderr)
            sys.exit(1)
    else:
        config_path = find_config()

    configure_logging(args.log_level)
    logger = logging.getLogger("omni_bot_sdk.__main__")

    if config_path:
        logger.info(f"使用配置文件: {config_path}")
    else:
        logger.warning("未找到配置文件，将使用默认配置（请创建 config.yaml）")

    try:
        bot = Bot(config_path=config_path or "config.yaml")
        bot.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"启动失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
