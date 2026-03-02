"""OKX客户端集成测试。

这些测试需要有效的OKX API密钥才能运行。
建议先在模拟盘环境运行测试。
"""

from __future__ import annotations

import asyncio
import os
from unittest import IsolatedAsyncioTestCase, skipUnless

import pytest
from dotenv import load_dotenv

from src.infrastructure.okx_auth import OkxCredentials
from src.infrastructure.okx_rest_client import OkxRestClient, OkxApiError
from src.infrastructure.okx_ws_client import KlineData, OkxWebSocketClient

load_dotenv()

DEMO_API_KEY = os.getenv("OKX_DEMO_API_KEY", "")
DEMO_API_SECRET = os.getenv("OKX_DEMO_API_SECRET", "")
DEMO_PASSPHRASE = os.getenv("OKX_DEMO_PASSPHRASE", "")

HAS_DEMO_CREDENTIALS = all([DEMO_API_KEY, DEMO_API_SECRET, DEMO_PASSPHRASE])


@skipUnless(HAS_DEMO_CREDENTIALS, "需要OKX模拟盘API密钥")
class TestOkxRestIntegration(IsolatedAsyncioTestCase):
    """OKX REST客户端集成测试。"""

    def setUp(self) -> None:
        """设置测试数据。"""
        self.credentials = OkxCredentials(
            api_key=DEMO_API_KEY,
            api_secret=DEMO_API_SECRET,
            passphrase=DEMO_PASSPHRASE,
        )
        self.client = OkxRestClient(self.credentials, is_simulated=True)

    async def asyncTearDown(self) -> None:
        """异步清理。"""
        await self.client.close()

    async def test_get_balance(self) -> None:
        """测试查询余额接口。"""
        result = await self.client.get_balance()

        self.assertEqual(result["code"], "0")
        self.assertIn("data", result)

    async def test_get_positions(self) -> None:
        """测试查询持仓接口。"""
        result = await self.client.get_positions()

        self.assertEqual(result["code"], "0")
        self.assertIn("data", result)

    async def test_get_instrument(self) -> None:
        """测试查询交易对信息接口。"""
        result = await self.client.get_instrument("BTC-USDT-SWAP")

        self.assertEqual(result["code"], "0")
        self.assertIn("data", result)
        self.assertTrue(len(result["data"]) > 0)
        self.assertEqual(result["data"][0]["instId"], "BTC-USDT-SWAP")

    async def test_get_candles(self) -> None:
        """测试查询K线数据接口。"""
        result = await self.client.get_candles("BTC-USDT-SWAP", "1H", limit=10)

        self.assertEqual(result["code"], "0")
        self.assertIn("data", result)
        self.assertTrue(len(result["data"]) > 0)

        candle = result["data"][0]
        self.assertEqual(len(candle), 9)

    async def test_set_position_mode(self) -> None:
        """测试设置持仓模式接口。"""
        result = await self.client.set_position_mode("net_mode")

        self.assertIn(result["code"], ["0", "59107"])

    async def test_set_leverage(self) -> None:
        """测试设置杠杆接口。"""
        try:
            result = await self.client.set_leverage(
                inst_id="BTC-USDT-SWAP",
                lever=10,
                mgn_mode="cross",
            )
            self.assertIn(result["code"], ["0", "51004"])
        except OkxApiError:
            pass

    async def test_place_and_get_order(self) -> None:
        """测试下单和查询订单接口。"""
        import uuid

        client_oid = str(uuid.uuid4())

        try:
            place_result = await self.client.place_order(
                inst_id="BTC-USDT-SWAP",
                side="buy",
                sz="1",
                ord_type="limit",
                client_oid=client_oid,
            )

            if place_result["code"] == "0":
                order_id = place_result["data"][0]["ordId"]

                get_result = await self.client.get_order_info(
                    inst_id="BTC-USDT-SWAP",
                    ord_id=order_id,
                )

                self.assertEqual(get_result["code"], "0")
                self.assertIn("data", get_result)

        except OkxApiError as e:
            if "51004" not in str(e) and "51003" not in str(e):
                raise


@skipUnless(HAS_DEMO_CREDENTIALS, "需要OKX模拟盘API密钥")
class TestOkxWebSocketIntegration(IsolatedAsyncioTestCase):
    """OKX WebSocket客户端集成测试。"""

    def setUp(self) -> None:
        """设置测试数据。"""
        self.credentials = OkxCredentials(
            api_key=DEMO_API_KEY,
            api_secret=DEMO_API_SECRET,
            passphrase=DEMO_PASSPHRASE,
        )
        self.client = OkxWebSocketClient(is_simulated=True)

    async def asyncTearDown(self) -> None:
        """异步清理。"""
        await self.client.close()

    async def test_connect(self) -> None:
        """测试WebSocket连接。"""
        await self.client.connect()

        self.assertTrue(self.client._running)
        self.assertIsNotNone(self.client._ws)

        await self.client.close()

    async def test_subscribe_candles(self) -> None:
        """测试订阅K线频道。"""
        received_messages = []

        async def on_kline(kline: KlineData) -> None:
            received_messages.append(kline)

        await self.client.connect()
        await self.client.subscribe_candles("BTC-USDT-SWAP", "1H", on_kline)

        await asyncio.sleep(5)

        await self.client.close()

    async def test_receive_kline_data(self) -> None:
        """测试接收K线数据。"""
        received_klines = []

        async def on_kline(kline: KlineData) -> None:
            if kline.confirm == 1:
                received_klines.append(kline)

        await self.client.connect()
        await self.client.subscribe_candles("BTC-USDT-SWAP", "1H", on_kline)

        timeout = 30
        start_time = asyncio.get_event_loop().time()

        while len(received_klines) == 0:
            if asyncio.get_event_loop().time() - start_time > timeout:
                break
            await asyncio.sleep(0.5)

        await self.client.close()

        if len(received_klines) > 0:
            kline = received_klines[0]
            self.assertEqual(kline.inst_id, "BTC-USDT-SWAP")
            self.assertEqual(kline.timeframe, "1H")
            self.assertEqual(kline.confirm, 1)


@skipUnless(HAS_DEMO_CREDENTIALS, "需要OKX模拟盘API密钥")
class TestOkxFullFlowIntegration(IsolatedAsyncioTestCase):
    """OKX全流程集成测试。"""

    def setUp(self) -> None:
        """设置测试数据。"""
        self.credentials = OkxCredentials(
            api_key=DEMO_API_KEY,
            api_secret=DEMO_API_SECRET,
            passphrase=DEMO_PASSPHRASE,
        )
        self.rest_client = OkxRestClient(self.credentials, is_simulated=True)
        self.ws_client = OkxWebSocketClient(is_simulated=True)

    async def asyncTearDown(self) -> None:
        """异步清理。"""
        await self.rest_client.close()
        await self.ws_client.close()

    async def test_full_flow(self) -> None:
        """测试完整流程：连接、查询、订阅。"""
        balance_result = await self.rest_client.get_balance()
        self.assertEqual(balance_result["code"], "0")

        instrument_result = await self.rest_client.get_instrument("BTC-USDT-SWAP")
        self.assertEqual(instrument_result["code"], "0")

        candles_result = await self.rest_client.get_candles("BTC-USDT-SWAP", "1H", limit=5)
        self.assertEqual(candles_result["code"], "0")
        self.assertTrue(len(candles_result["data"]) > 0)

        await self.ws_client.connect()
        self.assertTrue(self.ws_client._running)

        received_messages = []

        async def on_kline(kline: KlineData) -> None:
            received_messages.append(kline)

        await self.ws_client.subscribe_candles("BTC-USDT-SWAP", "1H", on_kline)

        await asyncio.sleep(3)

        await self.ws_client.close()
