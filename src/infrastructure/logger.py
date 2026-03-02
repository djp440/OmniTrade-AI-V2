"""日志组件，支持同时输出到终端和文件。"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "FATAL"]

LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "FATAL": logging.CRITICAL,
}


class Logger:
    """自定义日志类，支持同时输出到终端和文件。"""

    _instance: Logger | None = None
    _initialized: bool = False

    def __new__(cls) -> Logger:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if Logger._initialized:
            return
        Logger._initialized = True

        self._logger = logging.getLogger("trade_bot")
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers = []

        self._console_handler: logging.Handler | None = None
        self._file_handler: logging.Handler | None = None
        self._log_dir: Path = Path("./logs")
        self._log_level: int = logging.INFO

    def initialize(
        self,
        log_dir: str = "./logs",
        log_level: LogLevel = "INFO",
        module_name: str = "trade_bot",
    ) -> None:
        """初始化日志配置。

        Args:
            log_dir: 日志文件存放目录
            log_level: 日志级别
            module_name: 日志模块名称
        """
        self._log_dir = Path(log_dir)
        self._log_level = LEVEL_MAP.get(log_level.upper(), logging.INFO)

        self._logger.name = module_name
        self._logger.setLevel(logging.DEBUG)

        for handler in self._logger.handlers[:]:
            self._logger.removeHandler(handler)
            handler.close()

        self._setup_console_handler()
        self._setup_file_handler()

    def _setup_console_handler(self) -> None:
        """设置控制台处理器。"""
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self._log_level)

        console_format = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_handler.setFormatter(console_format)

        self._logger.addHandler(console_handler)
        self._console_handler = console_handler

    def _setup_file_handler(self) -> None:
        """设置文件处理器。"""
        self._log_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        filename = f"trade_bot_{now.strftime('%Y%m%d_%H%M%S')}.log"
        log_file = self._log_dir / filename

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)

        file_format = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_format)

        self._logger.addHandler(file_handler)
        self._file_handler = file_handler

        self.info(f"日志文件已创建: {log_file}")

    def _log(self, level: int, message: str) -> None:
        """内部日志记录方法。"""
        self._logger.log(level, message)

    def debug(self, message: str) -> None:
        """记录DEBUG级别日志。"""
        self._log(logging.DEBUG, message)

    def info(self, message: str) -> None:
        """记录INFO级别日志。"""
        self._log(logging.INFO, message)

    def warning(self, message: str) -> None:
        """记录WARNING级别日志。"""
        self._log(logging.WARNING, message)

    def error(self, message: str) -> None:
        """记录ERROR级别日志。"""
        self._log(logging.ERROR, message)

    def fatal(self, message: str) -> None:
        """记录FATAL(CRITICAL)级别日志。"""
        self._log(logging.CRITICAL, message)

    def exception(self, message: str) -> None:
        """记录异常信息，自动包含堆栈。"""
        self._logger.exception(message)

    def audit(self, operation: str, params: dict, result: dict | None = None, order_id: str | None = None) -> None:
        """记录交易审计日志。

        Args:
            operation: 操作名称
            params: 操作参数
            result: 执行结果
            order_id: 订单ID
        """
        audit_msg = f"[AUDIT] operation={operation}"
        if params:
            audit_msg += f", params={params}"
        if result:
            audit_msg += f", result={result}"
        if order_id:
            audit_msg += f", order_id={order_id}"

        self.info(audit_msg)

    def get_log_file_path(self) -> Path | None:
        """获取当前日志文件路径。"""
        if self._file_handler and isinstance(self._file_handler, logging.FileHandler):
            return Path(self._file_handler.baseFilename)
        return None

    def flush(self) -> None:
        """刷新所有日志处理器。"""
        for handler in self._logger.handlers:
            handler.flush()

    def shutdown(self) -> None:
        """关闭所有日志处理器。"""
        self.flush()
        for handler in self._logger.handlers[:]:
            handler.close()
            self._logger.removeHandler(handler)


def get_logger() -> Logger:
    """获取日志实例（单例模式）。"""
    return Logger()
