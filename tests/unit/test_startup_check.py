"""启动自检单元测试"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.application.startup_check import (
    StartupCheckError,
    StartupChecker,
    handle_startup_error,
)
from src.infrastructure.config_loader import ConfigContainer


class TestStartupCheckError:
    """测试启动检查错误类"""

    def test_error_with_exit_code(self) -> None:
        """测试错误包含退出码"""
        error = StartupCheckError("测试错误", 2)

        assert str(error) == "测试错误"
        assert error.exit_code == 2


class TestStartupChecker:
    """测试启动检查器"""

    @pytest.fixture
    def checker(self) -> StartupChecker:
        """创建检查器实例"""
        return StartupChecker()

    @pytest.fixture
    def mock_config(self) -> ConfigContainer:
        """创建模拟配置"""
        config = MagicMock(spec=ConfigContainer)
        config.openai_api_key = "test-api-key"
        config.openai_base_url = "https://api.openai.com/v1"
        config.okx_demo = MagicMock()
        config.okx_real = MagicMock()
        config.app_config.global_config.demo_mode = True
        config.app_config.global_config.llm_model = "gpt-4o"
        config.app_config.global_config.td_mode = "isolated"
        config.app_config.trade_pairs = []
        return config

    @pytest.mark.asyncio
    async def test_check_config_loading_success(self, checker: StartupChecker) -> None:
        """测试配置加载成功"""
        with patch("src.application.startup_check.load_config") as mock_load:
            mock_config = MagicMock()
            mock_config.openai_api_key = "test-key"
            mock_config.app_config.global_config.demo_mode = True
            mock_config.okx_demo = MagicMock()
            mock_load.return_value = mock_config

            with patch.object(Path, "exists", return_value=True):
                await checker._check_config_loading()

                assert checker._config == mock_config

    @pytest.mark.asyncio
    async def test_check_config_loading_missing_env(self, checker: StartupChecker) -> None:
        """测试.env文件缺失"""
        with patch.object(Path, "exists", side_effect=[False, True, True]):
            with pytest.raises(StartupCheckError) as exc_info:
                await checker._check_config_loading()

            assert exc_info.value.exit_code == StartupChecker.EXIT_CONFIG_ERROR

    @pytest.mark.asyncio
    async def test_check_config_loading_missing_api_key(self, checker: StartupChecker) -> None:
        """测试API Key缺失"""
        with patch("src.application.startup_check.load_config") as mock_load:
            mock_config = MagicMock()
            mock_config.openai_api_key = ""
            mock_load.return_value = mock_config

            with patch.object(Path, "exists", return_value=True):
                with pytest.raises(StartupCheckError) as exc_info:
                    await checker._check_config_loading()

                assert exc_info.value.exit_code == StartupChecker.EXIT_CONFIG_ERROR

    @pytest.mark.asyncio
    async def test_check_okx_connection_success(self, checker: StartupChecker) -> None:
        """测试OKX连接成功"""
        checker._config = MagicMock()
        checker._config.app_config.global_config.demo_mode = True
        checker._config.okx_demo = MagicMock()
        checker._config.app_config.trade_pairs = []

        with patch("src.application.startup_check.OkxRestClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_balance = AsyncMock(return_value={"code": "0", "data": []})
            mock_client_class.return_value = mock_client

            await checker._check_okx_connection()

            assert checker._okx_client == mock_client
            mock_client.get_balance.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_okx_connection_failure(self, checker: StartupChecker) -> None:
        """测试OKX连接失败"""
        checker._config = MagicMock()
        checker._config.app_config.global_config.demo_mode = True
        checker._config.okx_demo = MagicMock()
        checker._config.app_config.trade_pairs = []

        with patch("src.application.startup_check.OkxRestClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_balance = AsyncMock(return_value={"code": "1", "msg": "错误"})
            mock_client_class.return_value = mock_client

            with pytest.raises(StartupCheckError) as exc_info:
                await checker._check_okx_connection()

            assert exc_info.value.exit_code == StartupChecker.EXIT_CONNECTION_ERROR

    @pytest.mark.asyncio
    async def test_check_position_setup_success(self, checker: StartupChecker) -> None:
        """测试持仓模式设置成功"""
        checker._config = MagicMock()
        checker._config.app_config.global_config.td_mode = "isolated"
        checker._config.app_config.trade_pairs = []

        checker._okx_client = AsyncMock()
        checker._okx_client.set_position_mode = AsyncMock(return_value={"code": "0"})
        checker._okx_client.set_leverage = AsyncMock(return_value={"code": "0"})

        await checker._check_position_setup()

        checker._okx_client.set_position_mode.assert_called_once_with("net_mode")

    @pytest.mark.asyncio
    async def test_check_llm_connection_success(self, checker: StartupChecker) -> None:
        """测试LLM连接成功"""
        checker._config = MagicMock()
        checker._config.openai_api_key = "test-key"
        checker._config.openai_base_url = "https://api.openai.com/v1"
        checker._config.app_config.global_config.llm_model = "gpt-4o"

        with patch("src.application.startup_check.LLMClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.chat = AsyncMock(return_value="OK")
            mock_client_class.return_value = mock_client

            await checker._check_llm_connection()

            assert checker._llm_client == mock_client

    @pytest.mark.asyncio
    async def test_check_llm_connection_failure(self, checker: StartupChecker) -> None:
        """测试LLM连接失败"""
        checker._config = MagicMock()
        checker._config.openai_api_key = "test-key"
        checker._config.app_config.global_config.llm_model = "gpt-4o"

        with patch("src.application.startup_check.LLMClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.chat = AsyncMock(side_effect=Exception("连接失败"))
            mock_client_class.return_value = mock_client

            with pytest.raises(StartupCheckError) as exc_info:
                await checker._check_llm_connection()

            assert exc_info.value.exit_code == StartupChecker.EXIT_CONNECTION_ERROR

    @pytest.mark.asyncio
    async def test_run_all_checks_success(self, checker: StartupChecker) -> None:
        """测试所有检查通过"""
        mock_config = MagicMock()

        with patch.object(checker, "_check_config_loading", AsyncMock()) as mock_check1:
            with patch.object(checker, "_check_okx_connection", AsyncMock()) as mock_check2:
                with patch.object(checker, "_check_position_setup", AsyncMock()) as mock_check3:
                    with patch.object(checker, "_check_llm_connection", AsyncMock()) as mock_check4:
                        with patch.object(checker, "_check_llm_vision", AsyncMock()) as mock_check5:
                            checker._config = mock_config

                            result = await checker.run_all_checks()

                            assert result == mock_config
                            mock_check1.assert_called_once()
                            mock_check2.assert_called_once()
                            mock_check3.assert_called_once()
                            mock_check4.assert_called_once()
                            mock_check5.assert_called_once()


class TestHandleStartupError:
    """测试启动错误处理"""

    def test_handle_startup_error(self) -> None:
        """测试错误处理函数"""
        error = StartupCheckError("测试错误", 2)

        with patch("src.application.startup_check.Logger") as mock_logger_class:
            mock_logger = MagicMock()
            mock_logger_class.return_value = mock_logger

            with pytest.raises(SystemExit) as exc_info:
                handle_startup_error(error)

            assert exc_info.value.code == 2
            mock_logger.error.assert_called()
