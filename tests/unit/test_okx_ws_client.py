"""OKX WebSocket客户端单元测试。"""

import asyncio
import json
import sys
from unittest import IsolatedAsyncioTestCase, mock

import aiohttp
import pytest

from src.infrastructure.okx_ws_client import KlineData, OkxWebSocketClient, Subscription


class TestKlineData(IsolatedAsyncioTestCase):
    """KlineData测试类。"""

    def test_from_ws_message_complete(self) -> None:
        """测试从完整WebSocket消息解析K线数据。"""
        data = [
            "1705312800000",
            "42000.5",
            "42500.0",
            "41800.0",
            "42300.5",
            "100.5",
            "4230000",
            1
        ]

        kline = KlineData.from_ws_message(data, "BTC-USDT-SWAP", "1H")

        self.assertEqual(kline.timestamp, "1705312800000")
        self.assertEqual(kline.open, "42000.5")
        self.assertEqual(kline.high, "42500.0")
        self.assertEqual(kline.low, "41800.0")
        self.assertEqual(kline.close, "42300.5")
        self.assertEqual(kline.vol, "100.5")
        self.assertEqual(kline.vol_ccy, "4230000")
        self.assertEqual(kline.confirm, 1)
        self.assertEqual(kline.inst_id, "BTC-USDT-SWAP")
        self.assertEqual(kline.timeframe, "1H")

    def test_from_ws_message_minimal(self) -> None:
        """测试从最小WebSocket消息解析K线数据。"""
        data = [
            "1705312800000",
            "42000.5",
            "42500.0",
            "41800.0",
            "42300.5",
            "100.5"
        ]

        kline = KlineData.from_ws_message(data, "ETH-USDT-SWAP", "4H")

        self.assertEqual(kline.timestamp, "1705312800000")
        self.assertEqual(kline.open, "42000.5")
        self.assertEqual(kline.high, "42500.0")
        self.assertEqual(kline.low, "41800.0")
        self.assertEqual(kline.close, "42300.5")
        self.assertEqual(kline.vol, "100.5")
        self.assertEqual(kline.vol_ccy, "")
        self.assertEqual(kline.confirm, 0)
        self.assertEqual(kline.inst_id, "ETH-USDT-SWAP")
        self.assertEqual(kline.timeframe, "4H")

    def test_from_ws_message_not_confirmed(self) -> None:
        """测试解析未收盘的K线数据（confirm=0）。"""
        data = [
            "1705312800000",
            "42000.5",
            "42500.0",
            "41800.0",
            "42300.5",
            "100.5",
            "4230000",
            0
        ]

        kline = KlineData.from_ws_message(data, "BTC-USDT-SWAP", "1H")

        self.assertEqual(kline.confirm, 0)


class TestOkxWebSocketClient(IsolatedAsyncioTestCase):
    """OkxWebSocketClient测试类。"""

    def setUp(self) -> None:
        """设置测试数据。"""
        self.client = OkxWebSocketClient(is_simulated=False)

    async def asyncTearDown(self) -> None:
        """异步清理。"""
        await self.client.close()

    def test_init_real_trading(self) -> None:
        """测试实盘客户端初始化。"""
        client = OkxWebSocketClient(is_simulated=False)

        self.assertFalse(client._is_simulated)
        self.assertEqual(client._endpoint, OkxWebSocketClient.WS_ENDPOINT_REAL)
        self.assertIsNone(client._credentials)
        self.assertIsNone(client._signer)

    def test_init_simulated_trading(self) -> None:
        """测试模拟盘客户端初始化。"""
        client = OkxWebSocketClient(is_simulated=True)

        self.assertTrue(client._is_simulated)
        self.assertEqual(client._endpoint, OkxWebSocketClient.WS_ENDPOINT_DEMO)

    def test_set_message_handler(self) -> None:
        """测试设置消息处理器。"""
        async def handler(channel: str, data: dict) -> None:
            pass

        self.client.set_message_handler(handler)
        self.assertEqual(self.client._message_handler, handler)

    async def test_subscribe_candles(self) -> None:
        """测试订阅K线频道。"""
        callback_called = False

        async def callback(kline: KlineData) -> None:
            nonlocal callback_called
            callback_called = True

        await self.client.subscribe_candles("BTC-USDT-SWAP", "1H", callback)

        sub_key = "candle1H:BTC-USDT-SWAP"
        self.assertIn(sub_key, self.client._subscriptions)

        subscription = self.client._subscriptions[sub_key]
        self.assertEqual(subscription.channel, "candle1H")
        self.assertEqual(subscription.inst_id, "BTC-USDT-SWAP")
        self.assertIsNotNone(subscription.callback)

    async def test_unsubscribe(self) -> None:
        """测试取消订阅。"""
        await self.client.subscribe_candles("BTC-USDT-SWAP", "1H")

        sub_key = "candle1H:BTC-USDT-SWAP"
        self.assertIn(sub_key, self.client._subscriptions)

        await self.client.unsubscribe("candle1H", "BTC-USDT-SWAP")

        self.assertNotIn(sub_key, self.client._subscriptions)

    async def test_handle_message_kline(self) -> None:
        """测试处理K线消息。"""
        received_klines = []

        async def callback(kline: KlineData) -> None:
            received_klines.append(kline)

        await self.client.subscribe_candles("BTC-USDT-SWAP", "1H", callback)

        message = json.dumps({
            "arg": {"channel": "candle1H", "instId": "BTC-USDT-SWAP"},
            "data": [[
                "1705312800000",
                "42000.5",
                "42500.0",
                "41800.0",
                "42300.5",
                "100.5",
                "4230000",
                1
            ]]
        })

        await self.client._handle_message(message)

        await asyncio.sleep(0.1)

        self.assertEqual(len(received_klines), 1)
        self.assertEqual(received_klines[0].inst_id, "BTC-USDT-SWAP")
        self.assertEqual(received_klines[0].confirm, 1)

    async def test_handle_message_event(self) -> None:
        """测试处理事件消息（subscribe/unsubscribe/error）。"""
        subscribe_message = json.dumps({"event": "subscribe", "arg": {"channel": "candle1H"}})
        unsubscribe_message = json.dumps({"event": "unsubscribe"})
        error_message = json.dumps({"event": "error", "msg": "Invalid channel"})

        await self.client._handle_message(subscribe_message)
        await self.client._handle_message(unsubscribe_message)
        await self.client._handle_message(error_message)

    async def test_handle_message_invalid_json(self) -> None:
        """测试处理无效JSON消息。"""
        await self.client._handle_message("invalid json{")

    async def test_handle_message_no_matching_subscription(self) -> None:
        """测试处理无匹配订阅的消息。"""
        message = json.dumps({
            "arg": {"channel": "candle4H", "instId": "ETH-USDT-SWAP"},
            "data": []
        })

        await self.client._handle_message(message)

    async def test_close(self) -> None:
        """测试关闭连接。"""
        self.client._running = True

        mock_ws = mock.AsyncMock()
        mock_ws.closed = False
        self.client._ws = mock_ws

        mock_session = mock.AsyncMock()
        mock_session.closed = False
        self.client._session = mock_session

        await self.client.close()

        self.assertFalse(self.client._running)
        mock_ws.close.assert_called_once()
        mock_session.close.assert_called_once()


class TestOkxWebSocketClientReconnect(IsolatedAsyncioTestCase):
    """OkxWebSocketClient重连测试类。"""

    def setUp(self) -> None:
        """设置测试数据。"""
        self.client = OkxWebSocketClient(is_simulated=False)

    async def asyncTearDown(self) -> None:
        """异步清理。"""
        await self.client.close()

    async def test_reconnect_success(self) -> None:
        """测试重连成功。"""
        mock_ws = mock.AsyncMock()
        mock_ws.closed = False
        mock_ws.close = mock.AsyncMock()
        mock_ws.send_str = mock.AsyncMock()

        self.client._session = mock.AsyncMock()
        self.client._session.closed = False
        self.client._session.ws_connect = mock.AsyncMock(return_value=mock_ws)
        self.client._running = True

        await self.client._reconnect()

        self.client._session.ws_connect.assert_called_once()

    async def test_reconnect_failure_exits(self) -> None:
        """测试重连失败5次后退出程序。"""
        self.client._session = mock.AsyncMock()
        self.client._session.closed = False
        self.client._session.ws_connect = mock.AsyncMock(side_effect=ConnectionError("Connection failed"))
        self.client._running = True

        with mock.patch("sys.exit") as mock_exit:
            await self.client._reconnect()
            mock_exit.assert_called_once_with(1)

    async def test_resubscribe_on_reconnect(self) -> None:
        """测试重连后重新订阅。"""
        mock_ws = mock.AsyncMock()
        mock_ws.closed = False
        mock_ws.close = mock.AsyncMock()
        mock_ws.send_str = mock.AsyncMock()

        await self.client.subscribe_candles("BTC-USDT-SWAP", "1H")

        self.client._running = True
        self.client._session = mock.AsyncMock()
        self.client._session.closed = False
        self.client._session.ws_connect = mock.AsyncMock(return_value=mock_ws)

        await self.client._reconnect()

        sent_messages = [call[0][0] for call in mock_ws.send_str.call_args_list]
        self.assertTrue(any("subscribe" in msg for msg in sent_messages))
