"""日志组件单元测试。"""

import logging
import os
import tempfile
from pathlib import Path

import pytest

from src.infrastructure.logger import Logger, get_logger


class TestLogger:
    """测试日志组件。"""

    def setup_method(self):
        """每个测试方法前重置日志实例。"""
        Logger._instance = None
        Logger._initialized = False

    def teardown_method(self):
        """每个测试方法后关闭日志处理器。"""
        try:
            logger = Logger()
            logger.shutdown()
        except Exception:
            pass
        Logger._instance = None
        Logger._initialized = False

    def test_singleton_pattern(self):
        """测试单例模式。"""
        logger1 = get_logger()
        logger2 = get_logger()
        assert logger1 is logger2

    def test_log_level_mapping(self):
        """测试日志级别映射。"""
        from src.infrastructure.logger import LEVEL_MAP

        assert LEVEL_MAP["DEBUG"] == logging.DEBUG
        assert LEVEL_MAP["INFO"] == logging.INFO
        assert LEVEL_MAP["WARNING"] == logging.WARNING
        assert LEVEL_MAP["ERROR"] == logging.ERROR
        assert LEVEL_MAP["FATAL"] == logging.CRITICAL

    def test_initialize_creates_log_file(self):
        """测试初始化创建日志文件。"""
        log_dir = Path(tempfile.mkdtemp())
        try:
            logger = get_logger()
            logger.initialize(log_dir=str(log_dir), log_level="INFO")

            log_file = logger.get_log_file_path()
            assert log_file is not None
            assert log_file.exists()
            assert log_file.parent == log_dir
            assert log_file.name.startswith("trade_bot_")
            assert log_file.suffix == ".log"
        finally:
            logger.shutdown()
            for f in log_dir.glob("*.log"):
                try:
                    f.unlink()
                except PermissionError:
                    pass
            try:
                log_dir.rmdir()
            except Exception:
                pass

    def test_log_file_naming_format(self):
        """测试日志文件命名格式。"""
        log_dir = Path(tempfile.mkdtemp())
        try:
            logger = get_logger()
            logger.initialize(log_dir=str(log_dir), log_level="INFO")

            log_file = logger.get_log_file_path()
            name = log_file.name

            assert name.startswith("trade_bot_")
            assert name.endswith(".log")

            middle = name.replace("trade_bot_", "").replace(".log", "")
            parts = middle.split("_")
            assert len(parts) == 2

            date_part = parts[0]
            time_part = parts[1]

            assert len(date_part) == 8
            assert date_part.isdigit()
            assert len(time_part) == 6
            assert time_part.isdigit()
        finally:
            logger.shutdown()
            for f in log_dir.glob("*.log"):
                try:
                    f.unlink()
                except PermissionError:
                    pass
            try:
                log_dir.rmdir()
            except Exception:
                pass

    def test_log_levels(self):
        """测试不同日志级别记录。"""
        log_dir = Path(tempfile.mkdtemp())
        try:
            logger = get_logger()
            logger.initialize(log_dir=str(log_dir), log_level="DEBUG")

            logger.debug("debug message")
            logger.info("info message")
            logger.warning("warning message")
            logger.error("error message")
            logger.fatal("fatal message")

            logger.flush()

            log_file = logger.get_log_file_path()
            content = log_file.read_text(encoding="utf-8")

            assert "[DEBUG]" in content
            assert "[INFO]" in content
            assert "[WARNING]" in content
            assert "[ERROR]" in content
            assert "[CRITICAL]" in content
            assert "debug message" in content
            assert "info message" in content
            assert "warning message" in content
            assert "error message" in content
            assert "fatal message" in content
        finally:
            logger.shutdown()
            for f in log_dir.glob("*.log"):
                try:
                    f.unlink()
                except PermissionError:
                    pass
            try:
                log_dir.rmdir()
            except Exception:
                pass

    def test_log_format(self):
        """测试日志格式。"""
        log_dir = Path(tempfile.mkdtemp())
        try:
            logger = get_logger()
            logger.initialize(log_dir=str(log_dir), log_level="INFO")

            logger.info("test message")
            logger.flush()

            log_file = logger.get_log_file_path()
            content = log_file.read_text(encoding="utf-8")

            assert "[" in content
            assert "]" in content
            assert "[INFO]" in content
            assert "test message" in content
        finally:
            logger.shutdown()
            for f in log_dir.glob("*.log"):
                try:
                    f.unlink()
                except PermissionError:
                    pass
            try:
                log_dir.rmdir()
            except Exception:
                pass

    def test_audit_log(self):
        """测试审计日志。"""
        log_dir = Path(tempfile.mkdtemp())
        try:
            logger = get_logger()
            logger.initialize(log_dir=str(log_dir), log_level="INFO")

            logger.audit(
                operation="place_order",
                params={"inst_id": "BTC-USDT-SWAP", "side": "buy"},
                result={"success": True},
                order_id="12345",
            )
            logger.flush()

            log_file = logger.get_log_file_path()
            content = log_file.read_text(encoding="utf-8")

            assert "[AUDIT]" in content
            assert "operation=place_order" in content
            assert "BTC-USDT-SWAP" in content
            assert "order_id=12345" in content
        finally:
            logger.shutdown()
            for f in log_dir.glob("*.log"):
                try:
                    f.unlink()
                except PermissionError:
                    pass
            try:
                log_dir.rmdir()
            except Exception:
                pass

    def test_log_directory_created(self):
        """测试日志目录自动创建。"""
        base_dir = Path(tempfile.mkdtemp())
        log_dir = base_dir / "nested" / "logs"
        assert not log_dir.exists()

        try:
            logger = get_logger()
            logger.initialize(log_dir=str(log_dir), log_level="INFO")

            assert log_dir.exists()
        finally:
            logger.shutdown()
            import shutil
            try:
                shutil.rmtree(base_dir)
            except Exception:
                pass

    def test_flush_and_shutdown(self):
        """测试刷新和关闭。"""
        log_dir = Path(tempfile.mkdtemp())
        try:
            logger = get_logger()
            logger.initialize(log_dir=str(log_dir), log_level="INFO")

            logger.info("before flush")
            logger.flush()
            logger.info("after flush")
            logger.shutdown()

            log_file = logger.get_log_file_path()
            if log_file and log_file.exists():
                content = log_file.read_text(encoding="utf-8")
                assert "before flush" in content
        finally:
            for f in log_dir.glob("*.log"):
                try:
                    f.unlink()
                except PermissionError:
                    pass
            try:
                log_dir.rmdir()
            except Exception:
                pass

    def test_multiple_initialize(self):
        """测试多次初始化。"""
        log_dir = Path(tempfile.mkdtemp())
        try:
            logger = get_logger()
            logger.initialize(log_dir=str(log_dir), log_level="INFO")

            first_log_file = logger.get_log_file_path()

            logger.initialize(log_dir=str(log_dir), log_level="DEBUG")

            second_log_file = logger.get_log_file_path()

            assert first_log_file == second_log_file
        finally:
            logger.shutdown()
            for f in log_dir.glob("*.log"):
                try:
                    f.unlink()
                except PermissionError:
                    pass
            try:
                log_dir.rmdir()
            except Exception:
                pass
