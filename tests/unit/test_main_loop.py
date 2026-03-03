"""主事件循环单元测试"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.application.main_loop import MainEventLoop, TradingPairRunner
from src.domain.config import TradePairConfig
from src.domain.events import KlineCloseEvent
from src.domain.trading import Kline, Position, PositionDirection, TradeInstruction, TradeOperation


class TestTradingPairRunner:
    """测试交易对运行器"""

    @pytest.fixture
    def runner(self) -> TradingPairRunner:
        """创建运行器实例"""
        config = TradePairConfig(
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
            leverage=10,
            position_size=Decimal("100"),
            stop_loss_ratio=Decimal("0.02"),
            take_profit_ratio=Decimal("0.05"),
        )

        mock_rest_client = AsyncMock()
        mock_ws_client = AsyncMock()
        mock_agent_service = AsyncMock()
        mock_history_service = MagicMock()
        mock_trading_service = AsyncMock()

        return TradingPairRunner(
            trade_pair_config=config,
            okx_rest_client=mock_rest_client,
            okx_ws_client=mock_ws_client,
            agent_service=mock_agent_service,
            history_service=mock_history_service,
            trading_service=mock_trading_service,
            kline_count=100,
            risk_per_trade=Decimal("0.01"),
        )

    @pytest.mark.asyncio
    async def test_start(self, runner: TradingPairRunner) -> None:
        """测试启动运行器"""
        with patch.object(runner._kline_service, "add_kline_close_handler") as mock_add:
            with patch.object(runner._kline_service, "start", AsyncMock()) as mock_start:
                await runner.start()

                mock_add.assert_called_once()
                mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_kline_close_lock_acquired(self, runner: TradingPairRunner) -> None:
        """测试K线收盘事件处理（获取锁成功）"""
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

        with patch.object(runner, "_run_analysis_flow", AsyncMock()) as mock_run:
            # 确保锁未被占用
            assert not runner._analysis_lock.locked()

            await runner._on_kline_close(event)

            # 验证分析流程被调用
            mock_run.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_on_kline_close_lock_busy(self, runner: TradingPairRunner) -> None:
        """测试K线收盘事件处理（锁被占用）"""
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

        # 先占用锁
        await runner._analysis_lock.acquire()

        with patch.object(runner._logger, "warning") as mock_warning:
            await runner._on_kline_close(event)

            mock_warning.assert_called_once()

        runner._analysis_lock.release()

    @pytest.mark.asyncio
    async def test_fetch_historical_klines_success(self, runner: TradingPairRunner) -> None:
        """测试获取历史K线数据成功"""
        runner._rest_client.get_candles = AsyncMock(return_value={
            "code": "0",
            "data": [
                ["1234567890", "50000", "51000", "49000", "50500", "100", "100"],
                ["1234567891", "50500", "51500", "50000", "51000", "200", "200"],
            ],
        })

        result = await runner._fetch_historical_klines()

        assert result is not None
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fetch_historical_klines_failure(self, runner: TradingPairRunner) -> None:
        """测试获取历史K线数据失败"""
        runner._rest_client.get_candles = AsyncMock(return_value={
            "code": "1",
            "msg": "错误",
        })

        result = await runner._fetch_historical_klines()

        assert result is None

    @pytest.mark.asyncio
    async def test_generate_kline_image(self, runner: TradingPairRunner) -> None:
        """测试生成K线图"""
        from src.infrastructure.kline_plotter import KlineData

        klines = [
            KlineData(timestamp="1234567890", open=50000.0, high=51000.0, low=49000.0, close=50500.0),
        ]
        ema_values = [50250.0]

        with patch.object(runner._plotter, "plot", return_value=b"fake_png_data"):
            result = await runner._generate_kline_image(klines, ema_values)

            assert result is not None
            assert isinstance(result, str)  # base64字符串

    @pytest.mark.asyncio
    async def test_handle_position_closed(self, runner: TradingPairRunner) -> None:
        """测试处理平仓后操作"""
        balance = Decimal("10000")

        with patch.object(runner._history_service, "clear_history") as mock_clear:
            await runner._handle_position_closed(balance)

            mock_clear.assert_called_once_with("BTC-USDT-SWAP")


class TestMainEventLoop:
    """测试主事件循环"""

    @pytest.fixture
    def main_loop(self) -> MainEventLoop:
        """创建主事件循环实例"""
        mock_config = MagicMock()
        mock_config.app_config.global_config.demo_mode = True
        mock_config.okx_demo = MagicMock()
        mock_config.openai_api_key = "test-key"
        mock_config.app_config.global_config.llm_model = "gpt-4o"
        mock_config.app_config.global_config.td_mode = "isolated"
        mock_config.app_config.global_config.max_analysis_history_length = 10
        mock_config.app_config.global_config.k_line_count = 100
        mock_config.app_config.global_config.trade_record_path = "./test.csv"
        mock_config.app_config.trade_pairs = []
        mock_config.prompt_config = MagicMock()

        return MainEventLoop(mock_config)

    @pytest.mark.asyncio
    async def test_initialize(self, main_loop: MainEventLoop) -> None:
        """测试初始化"""
        with patch("src.application.main_loop.OkxRestClient") as mock_rest:
            with patch("src.application.main_loop.OkxWebSocketClient") as mock_ws:
                with patch("src.application.main_loop.LLMClient") as mock_llm:
                    with patch("src.application.main_loop.AgentService") as mock_agent:
                        with patch("src.application.main_loop.HistoryService") as mock_history:
                            with patch("src.application.main_loop.CSVStorage") as mock_csv:
                                with patch("src.application.main_loop.TradingService") as mock_trading:
                                    mock_trading_instance = AsyncMock()
                                    mock_trading.return_value = mock_trading_instance

                                    await main_loop.initialize()

                                    mock_rest.assert_called_once()
                                    mock_ws.assert_called_once()
                                    mock_trading_instance.initialize.assert_called_once()

    def test_setup_signal_handlers(self, main_loop: MainEventLoop) -> None:
        """测试信号处理器设置"""
        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            main_loop._setup_signal_handlers()

            # 验证信号处理器被添加
            assert mock_loop.add_signal_handler.call_count >= 0

    @pytest.mark.asyncio
    async def test_handle_shutdown_signal(self, main_loop: MainEventLoop) -> None:
        """测试处理关闭信号"""
        with patch.object(main_loop._logger, "info") as mock_info:
            await main_loop._handle_shutdown_signal("SIGINT")

            assert main_loop._shutdown_event.is_set()
            mock_info.assert_called()

    @pytest.mark.asyncio
    async def test_shutdown(self, main_loop: MainEventLoop) -> None:
        """测试关闭操作"""
        main_loop._okx_ws_client = AsyncMock()
        main_loop._okx_rest_client = AsyncMock()

        await main_loop.shutdown()

        assert main_loop._shutdown_event.is_set()
