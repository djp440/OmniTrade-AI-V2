"""K线服务集成测试

这些测试需要有效的OKX API密钥才能运行。
建议先在模拟盘环境运行测试。
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from unittest import IsolatedAsyncioTestCase, skipUnless

from dotenv import load_dotenv

from src.domain.config import TradePairConfig
from src.domain.events import KlineCloseEvent
from src.infrastructure.okx_auth import OkxCredentials
from src.infrastructure.okx_rest_client import OkxRestClient
from src.infrastructure.okx_ws_client import KlineData as WSKlineData, OkxWebSocketClient
from src.services.kline_service import KlineService

# 从项目根目录的 config/.env 加载环境变量
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config", ".env")
load_dotenv(env_path)

DEMO_API_KEY = os.getenv("OKX_DEMO_API_KEY", "")
DEMO_API_SECRET = os.getenv("OKX_DEMO_API_SECRET", "")
DEMO_PASSPHRASE = os.getenv("OKX_DEMO_PASSPHRASE", "")

HAS_DEMO_CREDENTIALS = all([DEMO_API_KEY, DEMO_API_SECRET, DEMO_PASSPHRASE])


@skipUnless(HAS_DEMO_CREDENTIALS, "需要OKX模拟盘API密钥")
class TestKlineServiceIntegration(IsolatedAsyncioTestCase):
    """K线服务集成测试类"""

    def setUp(self) -> None:
        """设置测试数据"""
        self.credentials = OkxCredentials(
            api_key=DEMO_API_KEY,
            api_secret=DEMO_API_SECRET,
            passphrase=DEMO_PASSPHRASE,
        )
        self.rest_client = OkxRestClient(self.credentials, is_simulated=True)
        self.ws_client = OkxWebSocketClient(self.credentials, is_simulated=True)

        self.trade_pair_config = TradePairConfig(
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
            leverage=10,
            position_size=Decimal("100"),
            stop_loss_ratio=Decimal("0.02"),
            take_profit_ratio=Decimal("0.05"),
        )

        self.service = KlineService(
            rest_client=self.rest_client,
            ws_client=self.ws_client,
            trade_pair_config=self.trade_pair_config,
            kline_count=100,
        )

    async def asyncTearDown(self) -> None:
        """异步清理"""
        await self.rest_client.close()
        await self.ws_client.close()

    async def test_fetch_klines_from_okx(self) -> None:
        """测试从OKX获取K线数据"""
        klines = await self.service._fetch_klines()

        self.assertGreater(len(klines), 0)
        self.assertLessEqual(len(klines), 100)

        kline = klines[0]
        self.assertGreater(kline.open, Decimal("0"))

    async def test_get_klines_with_ema_integration(self) -> None:
        """测试获取K线数据并计算EMA、生成图表"""
        klines, ema_values, base64_image = await self.service.get_klines_with_ema()

        self.assertGreaterEqual(len(klines), 20)
        self.assertEqual(len(klines), len(ema_values))

        self.assertTrue(isinstance(base64_image, str))
        self.assertGreater(len(base64_image), 100)

        import base64
        png_data = base64.b64decode(base64_image)
        self.assertTrue(png_data.startswith(b"\x89PNG"))

    async def test_get_current_price_integration(self) -> None:
        """测试获取当前价格"""
        price = await self.service.get_current_price()

        self.assertGreater(price, Decimal("0"))

    async def test_kline_close_event_flow(self) -> None:
        """测试K线收盘事件完整流程"""
        events_received = []

        async def handler(event: KlineCloseEvent) -> None:
            events_received.append(event)

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

        self.assertEqual(len(events_received), 1)
        event = events_received[0]
        self.assertEqual(event.inst_id, "BTC-USDT-SWAP")
        self.assertEqual(event.timeframe, "1H")
        self.assertEqual(event.kline.close, Decimal("42300.5"))


@skipUnless(HAS_DEMO_CREDENTIALS, "需要OKX模拟盘API密钥")
class TestKlineServiceWebSocketIntegration(IsolatedAsyncioTestCase):
    """K线服务WebSocket集成测试类"""

    def setUp(self) -> None:
        """设置测试数据"""
        self.credentials = OkxCredentials(
            api_key=DEMO_API_KEY,
            api_secret=DEMO_API_SECRET,
            passphrase=DEMO_PASSPHRASE,
        )
        self.rest_client = OkxRestClient(self.credentials, is_simulated=True)
        self.ws_client = OkxWebSocketClient(self.credentials, is_simulated=True)

        self.trade_pair_config = TradePairConfig(
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
            leverage=10,
            position_size=Decimal("100"),
            stop_loss_ratio=Decimal("0.02"),
            take_profit_ratio=Decimal("0.05"),
        )

        self.service = KlineService(
            rest_client=self.rest_client,
            ws_client=self.ws_client,
            trade_pair_config=self.trade_pair_config,
            kline_count=100,
        )

        self.received_events = []

    async def asyncTearDown(self) -> None:
        """异步清理"""
        await self.rest_client.close()
        await self.ws_client.close()

    async def _event_handler(self, event: KlineCloseEvent) -> None:
        """事件处理器"""
        self.received_events.append(event)

    async def test_websocket_subscription(self) -> None:
        """测试WebSocket订阅功能"""
        self.service.add_kline_close_handler(self._event_handler)

        await self.service.start()

        self.assertIn("candle1H:BTC-USDT-SWAP", self.ws_client._subscriptions)

    async def test_websocket_kline_event_processing(self) -> None:
        """测试WebSocket K线事件处理"""
        self.service.add_kline_close_handler(self._event_handler)
        await self.service.start()

        test_kline = WSKlineData(
            timestamp="1705312800000",
            open="42000.0",
            high="42500.0",
            low="41800.0",
            close="42300.0",
            vol="100.0",
            vol_ccy="4230000",
            confirm=1,
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
        )

        await self.service._on_kline_received(test_kline)

        self.assertEqual(len(self.received_events), 1)
        event = self.received_events[0]
        self.assertEqual(event.inst_id, "BTC-USDT-SWAP")
        self.assertEqual(event.kline.close, Decimal("42300.0"))
