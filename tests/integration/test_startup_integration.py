"""启动自检集成测试"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.application.startup_check import StartupCheckError, StartupChecker
from src.domain.trading import Position, PositionDirection


@pytest.mark.integration
class TestStartupCheckIntegration:
    """启动自检集成测试"""

    @pytest.fixture
    def checker(self) -> StartupChecker:
        """创建检查器实例"""
        return StartupChecker()

    @pytest.mark.asyncio
    async def test_full_startup_check_success(self, checker: StartupChecker) -> None:
        """测试完整启动检查成功流程"""

        # 模拟所有检查步骤
        with patch.object(checker, "_check_config_loading", AsyncMock()) as mock_config:
            with patch.object(checker, "_check_okx_connection", AsyncMock()) as mock_okx:
                with patch.object(checker, "_check_position_setup", AsyncMock()) as mock_position:
                    with patch.object(checker, "_check_llm_connection", AsyncMock()) as mock_llm:
                        with patch.object(checker, "_check_llm_vision", AsyncMock()) as mock_vision:
                            mock_config_obj = MagicMock()
                            checker._config = mock_config_obj

                            result = await checker.run_all_checks()

                            assert result == mock_config_obj
                            mock_config.assert_called_once()
                            mock_okx.assert_called_once()
                            mock_position.assert_called_once()
                            mock_llm.assert_called_once()
                            mock_vision.assert_called_once()

    @pytest.mark.asyncio
    async def test_startup_check_config_failure(self, checker: StartupChecker) -> None:
        """测试配置检查失败"""

        with patch.object(
            checker,
            "_check_config_loading",
            AsyncMock(side_effect=StartupCheckError("配置错误", 2)),
        ):
            with pytest.raises(StartupCheckError) as exc_info:
                await checker.run_all_checks()

            assert exc_info.value.exit_code == 2
            assert "配置错误" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_startup_check_okx_failure(self, checker: StartupChecker) -> None:
        """测试OKX连接检查失败"""

        with patch.object(checker, "_check_config_loading", AsyncMock()):
            with patch.object(
                checker,
                "_check_okx_connection",
                AsyncMock(side_effect=StartupCheckError("OKX连接失败", 3)),
            ):
                checker._config = MagicMock()

                with pytest.raises(StartupCheckError) as exc_info:
                    await checker.run_all_checks()

                assert exc_info.value.exit_code == 3

    @pytest.mark.asyncio
    async def test_check_okx_with_trade_pairs(self, checker: StartupChecker) -> None:
        """测试OKX检查包含交易对验证"""

        checker._config = MagicMock()
        checker._config.app_config.global_config.demo_mode = True
        checker._config.okx_demo = MagicMock()

        # 创建交易对配置
        trade_pair1 = MagicMock()
        trade_pair1.inst_id = "BTC-USDT-SWAP"
        trade_pair2 = MagicMock()
        trade_pair2.inst_id = "ETH-USDT-SWAP"
        checker._config.app_config.trade_pairs = [trade_pair1, trade_pair2]

        with patch("src.application.startup_check.OkxRestClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_balance = AsyncMock(return_value={"code": "0", "data": []})
            mock_client.get_instrument = AsyncMock(return_value={"code": "0", "data": []})
            mock_client_class.return_value = mock_client

            await checker._check_okx_connection()

            # 验证每个交易对都被检查
            assert mock_client.get_instrument.call_count == 2

    @pytest.mark.asyncio
    async def test_check_position_setup_with_trade_pairs(self, checker: StartupChecker) -> None:
        """测试持仓模式设置包含所有交易对"""

        checker._config = MagicMock()
        checker._config.app_config.global_config.td_mode = "isolated"

        trade_pair1 = MagicMock()
        trade_pair1.inst_id = "BTC-USDT-SWAP"
        trade_pair1.leverage = 10
        trade_pair2 = MagicMock()
        trade_pair2.inst_id = "ETH-USDT-SWAP"
        trade_pair2.leverage = 20
        checker._config.app_config.trade_pairs = [trade_pair1, trade_pair2]

        checker._okx_client = AsyncMock()
        checker._okx_client.set_position_mode = AsyncMock(return_value={"code": "0"})
        checker._okx_client.set_leverage = AsyncMock(return_value={"code": "0"})

        await checker._check_position_setup()

        # 验证持仓模式设置
        checker._okx_client.set_position_mode.assert_called_once_with("net_mode")
        # 验证每个交易对的杠杆设置
        assert checker._okx_client.set_leverage.call_count == 2

    @pytest.mark.asyncio
    async def test_check_llm_vision_with_image(self, checker: StartupChecker) -> None:
        """测试LLM图片解析能力检查"""

        checker._config = MagicMock()
        checker._config.app_config.global_config.llm_model = "gpt-4o"

        mock_llm_client = AsyncMock()
        mock_llm_client.chat = AsyncMock(return_value="这是一个上涨趋势图表")
        checker._llm_client = mock_llm_client

        with patch("src.application.startup_check.KlinePlotter") as mock_plotter_class:
            with patch("src.application.startup_check.EMACalculator") as mock_ema_class:
                mock_plotter = MagicMock()
                mock_plotter.plot = MagicMock(return_value=b"fake_png_data")
                mock_plotter_class.return_value = mock_plotter

                mock_ema = MagicMock()
                mock_ema.calculate = MagicMock(return_value=[50000.0, 50100.0])
                mock_ema_class.return_value = mock_ema

                await checker._check_llm_vision()

                # 验证LLM被调用且包含图片
                call_args = mock_llm_client.chat.call_args
                assert call_args.kwargs.get("image_data") is not None


@pytest.mark.integration
class TestMainLoopIntegration:
    """主事件循环集成测试"""

    @pytest.mark.asyncio
    async def test_main_loop_initialization(self) -> None:
        """测试主事件循环初始化"""
        from src.application.main_loop import MainEventLoop

        mock_config = MagicMock()
        mock_config.app_config.global_config.demo_mode = True
        mock_config.okx_demo = MagicMock()
        mock_config.openai_api_key = "test-key"
        mock_config.openai_base_url = "https://api.openai.com/v1"
        mock_config.app_config.global_config.llm_model = "gpt-4o"
        mock_config.app_config.global_config.td_mode = "isolated"
        mock_config.app_config.global_config.max_analysis_history_length = 10
        mock_config.app_config.global_config.k_line_count = 100
        mock_config.app_config.global_config.trade_record_path = "./test.csv"
        mock_config.app_config.trade_pairs = []
        mock_config.prompt_config = MagicMock()

        main_loop = MainEventLoop(mock_config)

        with patch("src.application.main_loop.OkxRestClient"):
            with patch("src.application.main_loop.OkxWebSocketClient"):
                with patch("src.application.main_loop.LLMClient"):
                    with patch("src.application.main_loop.TradingService") as mock_trading_class:
                        mock_trading = AsyncMock()
                        mock_trading_class.return_value = mock_trading

                        await main_loop.initialize()

                        # 验证交易服务被初始化
                        mock_trading.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_trading_pair_runner_analysis_flow(self) -> None:
        """测试交易对运行器分析流程"""
        from src.application.main_loop import TradingPairRunner
        from src.domain.config import TradePairConfig
        from src.domain.events import KlineCloseEvent
        from src.domain.trading import Kline

        config = TradePairConfig(
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
            leverage=10,
            position_size=Decimal("100"),
            stop_loss_ratio=Decimal("0.02"),
            take_profit_ratio=Decimal("0.05"),
        )

        mock_rest = AsyncMock()
        mock_ws = AsyncMock()
        mock_agent = AsyncMock()
        mock_history = MagicMock()
        mock_trading = AsyncMock()

        runner = TradingPairRunner(
            trade_pair_config=config,
            okx_rest_client=mock_rest,
            okx_ws_client=mock_ws,
            agent_service=mock_agent,
            history_service=mock_history,
            trading_service=mock_trading,
            kline_count=100,
            risk_per_trade=Decimal("0.01"),
        )

        # 模拟分析流程中的各个步骤
        mock_trading.get_account_balance = AsyncMock(return_value=Decimal("10000"))
        mock_trading.get_position = AsyncMock(return_value=Position(
            inst_id="BTC-USDT-SWAP",
            direction=PositionDirection.EMPTY,
            size=Decimal("0"),
            entry_price=Decimal("0"),
            stop_price=Decimal("0"),
            profit_price=Decimal("0"),
            unrealized_pnl=Decimal("0"),
        ))

        event = KlineCloseEvent(
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
            kline=Kline(
                timestamp=1234567890,
                open=Decimal("50000"),
                high=Decimal("51000"),
                low=Decimal("49000"),
                close=Decimal("50500"),
                vol=Decimal("100"),
                confirm=1,
            ),
        )

        # 由于分析流程复杂，这里主要验证流程能够启动
        # 详细的步骤测试在单元测试中完成
        with patch.object(runner, "_fetch_historical_klines", AsyncMock(return_value=None)):
            await runner._run_analysis_flow(event)

            # 验证余额和仓位查询被调用
            mock_trading.get_account_balance.assert_called_once()
            mock_trading.get_position.assert_called_once_with("BTC-USDT-SWAP")
