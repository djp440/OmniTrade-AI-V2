"""
日志组件
同时输出到终端和文件，支持级别配置
"""

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional


class Logger:
    """日志管理器"""

    LEVELS = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "FATAL": logging.CRITICAL,
    }

    _instance: Optional["Logger"] = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        log_dir: str = "./logs",
        log_level: str = "INFO",
        module_name: str = "trade_bot",
    ):
        if Logger._initialized:
            return

        self.log_dir = log_dir
        self.log_level = self.LEVELS.get(log_level.upper(), logging.INFO)
        self.module_name = module_name

        # 创建日志目录
        os.makedirs(log_dir, exist_ok=True)

        # 生成日志文件名（精确到秒）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(log_dir, f"{module_name}_{timestamp}.log")

        # 创建logger
        self.logger = logging.getLogger(module_name)
        self.logger.setLevel(self.log_level)
        self.logger.handlers = []  # 清除已有处理器

        # 格式化器
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # 终端处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.log_level)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        # 文件处理器
        file_handler = logging.FileHandler(self.log_file, encoding="utf-8")
        file_handler.setLevel(self.log_level)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        Logger._initialized = True

    def debug(self, message: str):
        """调试日志"""
        self.logger.debug(message)

    def info(self, message: str):
        """信息日志"""
        self.logger.info(message)

    def warning(self, message: str):
        """警告日志"""
        self.logger.warning(message)

    def error(self, message: str, exc_info: bool = True):
        """错误日志"""
        self.logger.error(message, exc_info=exc_info)

    def fatal(self, message: str, exc_info: bool = True):
        """致命错误日志"""
        self.logger.critical(message, exc_info=exc_info)

    def audit(self, operation: str, params: dict, result: dict):
        """
        审计日志

        Args:
            operation: 操作名称
            params: 操作参数
            result: 执行结果
        """
        message = f"AUDIT | Operation: {operation} | Params: {params} | Result: {result}"
        self.logger.info(message)

    def flush(self):
        """刷新日志缓冲区"""
        for handler in self.logger.handlers:
            handler.flush()


def get_logger(
    log_dir: str = "./logs",
    log_level: str = "INFO",
    module_name: str = "trade_bot",
) -> Logger:
    """
    获取日志器实例

    Args:
        log_dir: 日志目录
        log_level: 日志级别
        module_name: 模块名称

    Returns:
        Logger实例
    """
    return Logger(log_dir, log_level, module_name)
