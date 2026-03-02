"""K线服务单元测试"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest import IsolatedAsyncioTestCase, mock

import numpy as np

from src.domain.config import TradePairConfig
from src.domain.events import KlineCloseEvent
from src.domain.trading import Kline
from src.infrastructure.okx_ws_client import KlineData as WSKlineData
from src.services.kline_service import KlineService


class TestKlineService(IsolatedAsyncioTestCase):
    """K线服务测试类"""

    def setUp(self) -> None:
        """设置测试数据"""
        self.trade_pair_config = TradePairConfig(
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
            leverage=10,
            position_size=Decimal("100"),
            stop_loss_ratio=Decimal("0.02"),
            take_profit_ratio=Decimal("0.05"),
        )
        self.kline_count = 100

        self.mock_rest_client = mock.AsyncMock()
        self.mock_ws_client = mock.AsyncMock()

        self.service = KlineService(
            rest_client=self.mock_rest_client,
            ws_client=self.mock_ws_client,
            trade_pair_config=self.trade_pair_config,
            kline_count=self.kline_count,
        )

    async def asyncTearDown(self) -> None:
        """异步清理"""
        pass

    def test_init(self) -> None:
        """测试K线服务初始化"""
        self.assertEqual(self.service._config, self.trade_pair_config)
        self.assertEqual(self.service._kline_count, self.kline_count)
        self.assertEqual(len(self.service._kline_close_handlers), 0)

    def test_add_kline_close_handler(self) -> None:
        """测试添加K线收盘事件处理器"""

        async def handler(event: KlineCloseEvent) -> None:
            pass

        self.service.add_kline_close_handler(handler)
        self.assertEqual(len(self.service._kline_close_handlers), 1)
        self.assertEqual(self.service._kline_close_handlers[0], handler)

    async def test_start(self) -> None:
        """测试启动K线服务"""
        await self.service.start()

        self.mock_ws_client.subscribe_candles.assert_called_once_with(
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
            callback=self.service._on_kline_received,
        )

    async def test_on_kline_received_not_confirmed(self) -> None:
        """测试收到未收盘K线时不触发事件"""
        handler_called = False

        async def handler(event: KlineCloseEvent) -> None:
            nonlocal handler_called
            handler_called = True

        self.service.add_kline_close_handler(handler)

        kline_data = WSKlineData(
            timestamp="1705312800000",
            open="42000.5",
            high="42500.0",
            low="41800.0",
            close="42300.5",
            vol="100.5",
            vol_ccy="4230000",
            confirm=0,
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
        )

        await self.service._on_kline_received(kline_data)

        self.assertFalse(handler_called)

    async def test_on_kline_received_confirmed(self) -> None:
        """测试收到收盘K线时触发事件"""
        received_event: KlineCloseEvent | None = None

        async def handler(event: KlineCloseEvent) -> None:
            nonlocal received_event
            received_event = event

        self.service.add_kline_close_handler(handler)

        kline_data = WSKlineData(
            timestamp="1705312800000",
            open="42000.5",
            high="42500.0",
            low="41800.0",
            close="42300.5",
            vol="100.5",
            vol_ccy="4230000",
            confirm=1,
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
        )

        await self.service._on_kline_received(kline_data)

        self.assertIsNotNone(received_event)
        self.assertEqual(received_event.inst_id, "BTC-USDT-SWAP")
        self.assertEqual(received_event.timeframe, "1H")
        self.assertEqual(received_event.kline.timestamp, 1705312800000)
        self.assertEqual(received_event.kline.close, Decimal("42300.5"))

    async def test_on_kline_received_multiple_handlers(self) -> None:
        """测试多个事件处理器都被调用"""
        call_count = 0

        async def handler1(event: KlineCloseEvent) -> None:
            nonlocal call_count
            call_count += 1

        async def handler2(event: KlineCloseEvent) -> None:
            nonlocal call_count
            call_count += 1

        self.service.add_kline_close_handler(handler1)
        self.service.add_kline_close_handler(handler2)

        kline_data = WSKlineData(
            timestamp="1705312800000",
            open="42000.5",
            high="42500.0",
            low="41800.0",
            close="42300.5",
            vol="100.5",
            vol_ccy="4230000",
            confirm=1,
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
        )

        await self.service._on_kline_received(kline_data)

        self.assertEqual(call_count, 2)

    async def test_fetch_klines(self) -> None:
        """测试获取K线数据"""
        mock_response = {
            "code": "0",
            "data": [
                ["1705312800000", "42000.5", "42500.0", "41800.0", "42300.5", "100.5", "4230000", 1],
                ["1705309200000", "41800.0", "42200.0", "41600.0", "42000.5", "150.0", "6300000", 1],
            ],
        }
        self.mock_rest_client.get_candles.return_value = mock_response

        klines = await self.service._fetch_klines()

        self.mock_rest_client.get_candles.assert_called_once_with(
            inst_id="BTC-USDT-SWAP",
            bar="1H",
            limit=100,
        )

        self.assertEqual(len(klines), 2)
        self.assertEqual(klines[0].timestamp, 1705309200000)
        self.assertEqual(klines[1].timestamp, 1705312800000)

    async def test_get_klines_with_ema(self) -> None:
        """测试获取K线数据并计算EMA"""
        mock_data = []
        base_time = 1705312800000
        for i in range(25):
            mock_data.append([
                str(base_time - (24 - i) * 3600000),
                "42000.0",
                "42500.0",
                "41800.0",
                str(42000.0 + i * 100),
                "100.5",
                "4230000",
                1,
            ])

        mock_response = {"code": "0", "data": mock_data}
        self.mock_rest_client.get_candles.return_value = mock_response

        klines, ema_values, base64_image = await self.service.get_klines_with_ema()

        self.assertEqual(len(klines), 25)
        self.assertEqual(len(ema_values), 25)
        self.assertTrue(isinstance(base64_image, str))
        self.assertTrue(len(base64_image) > 0)

        self.assertTrue(np.isnan(ema_values[0]))
        self.assertFalse(np.isnan(ema_values[-1]))

    async def test_get_klines_with_ema_insufficient_data(self) -> None:
        """测试K线数据不足时抛出异常"""
        mock_response = {
            "code": "0",
            "data": [
                ["1705312800000", "42000.5", "42500.0", "41800.0", "42300.5", "100.5", "4230000", 1],
            ],
        }
        self.mock_rest_client.get_candles.return_value = mock_response

        with self.assertRaises(ValueError) as context:
            await self.service.get_klines_with_ema()

        self.assertIn("K线数据不足", str(context.exception))

    async def test_get_current_price(self) -> None:
        """测试获取当前价格"""
        mock_response = {
            "code": "0",
            "data": [
                ["1705312800000", "42000.5", "42500.0", "41800.0", "42300.5", "100.5", "4230000", 1],
            ],
        }
        self.mock_rest_client.get_candles.return_value = mock_response

        price = await self.service.get_current_price()

        self.assertEqual(price, Decimal("42300.5"))
        self.mock_rest_client.get_candles.assert_called_once_with(
            inst_id="BTC-USDT-SWAP",
            bar="1H",
            limit=1,
        )

    async def test_get_current_price_empty_data(self) -> None:
        """测试获取当前价格时数据为空"""
        mock_response = {"code": "0", "data": []}
        self.mock_rest_client.get_candles.return_value = mock_response

        with self.assertRaises(ValueError) as context:
            await self.service.get_current_price()

        self.assertIn("无法获取当前价格", str(context.exception))
