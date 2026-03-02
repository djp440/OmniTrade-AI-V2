"""OKX WebSocket客户端，基于aiohttp实现异步WebSocket连接。"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

import aiohttp

from .okx_auth import OkxCredentials, OkxSigner


class ChannelType(Enum):
    """WebSocket频道类型。"""

    CANDLES = "candle"
    TICKERS = "tickers"
    TRADES = "trades"


@dataclass
class KlineData:
    """K线数据模型。"""

    timestamp: str
    open: str
    high: str
    low: str
    close: str
    vol: str
    vol_ccy: str
    confirm: int
    inst_id: str = ""
    timeframe: str = ""

    @classmethod
    def from_ws_message(cls, data: list[Any], inst_id: str, timeframe: str) -> KlineData:
        """从WebSocket消息解析K线数据。

        Args:
            data: WebSocket返回的数据数组
            inst_id: 交易对ID
            timeframe: K线周期

        Returns:
            KlineData对象
        """
        return cls(
            timestamp=str(data[0]),
            open=str(data[1]),
            high=str(data[2]),
            low=str(data[3]),
            close=str(data[4]),
            vol=str(data[5]),
            vol_ccy=str(data[6]) if len(data) > 6 else "",
            confirm=int(data[7]) if len(data) > 7 else 0,
            inst_id=inst_id,
            timeframe=timeframe,
        )


@dataclass
class Subscription:
    """订阅信息。"""

    channel: str
    inst_id: str
    callback: Callable[[Any], Coroutine[Any, Any, None]] | None = None


class OkxWebSocketClient:
    """OKX WebSocket异步客户端。

    特性：
    - 自动重连（最多5次，间隔1s/2s/4s/8s/16s）
    - 重连失败触发程序退出
    - 重连时自动重新订阅所有频道
    - 订阅K线频道，解析confirm字段
    """

    WS_ENDPOINT_REAL = "wss://ws.okx.com:8443/ws/v5/public"
    WS_ENDPOINT_DEMO = "wss://wspap.okx.com:8443/ws/v5/public"
    MAX_RECONNECT_ATTEMPTS = 5
    RECONNECT_DELAYS = [1, 2, 4, 8, 16]
    PING_INTERVAL = 25

    def __init__(
        self,
        credentials: OkxCredentials | None = None,
        is_simulated: bool = False,
    ) -> None:
        """初始化WebSocket客户端。

        Args:
            credentials: OKX API凭证（公共频道可为None）
            is_simulated: 是否使用模拟盘
        """
        self._credentials = credentials
        self._is_simulated = is_simulated
        self._endpoint = self.WS_ENDPOINT_DEMO if is_simulated else self.WS_ENDPOINT_REAL
        self._signer = OkxSigner(credentials) if credentials else None

        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._subscriptions: dict[str, Subscription] = {}
        self._running = False
        self._receive_task: asyncio.Task[Any] | None = None
        self._ping_task: asyncio.Task[Any] | None = None
        self._message_handler: Callable[[str, Any], Coroutine[Any, Any, None]] | None = None

    def set_message_handler(
        self,
        handler: Callable[[str, Any], Coroutine[Any, Any, None]],
    ) -> None:
        """设置消息处理器。

        Args:
            handler: 消息处理函数，参数为(channel, data)
        """
        self._message_handler = handler

    async def connect(self) -> None:
        """建立WebSocket连接。

        Raises:
            ConnectionError: 连接失败且重试耗尽时抛出，触发程序退出
        """
        for attempt in range(self.MAX_RECONNECT_ATTEMPTS):
            try:
                if self._session is None or self._session.closed:
                    self._session = aiohttp.ClientSession()

                headers: dict[str, str] = {}
                if self._is_simulated:
                    headers["x-simulated-trading"] = "1"

                self._ws = await self._session.ws_connect(
                    self._endpoint,
                    headers=headers,
                    heartbeat=self.PING_INTERVAL,
                )

                self._running = True

                if self._receive_task:
                    self._receive_task.cancel()
                self._receive_task = asyncio.create_task(self._receive_loop())

                if self._ping_task:
                    self._ping_task.cancel()
                self._ping_task = asyncio.create_task(self._ping_loop())

                await self._resubscribe_all()

                return

            except Exception as e:
                delay = self.RECONNECT_DELAYS[attempt]
                if attempt < self.MAX_RECONNECT_ATTEMPTS - 1:
                    await asyncio.sleep(delay)
                else:
                    raise ConnectionError(
                        f"WebSocket连接失败，已重试{self.MAX_RECONNECT_ATTEMPTS}次: {e}"
                    ) from e

    async def _reconnect(self) -> None:
        """执行重连逻辑。"""
        if not self._running:
            return

        for attempt in range(self.MAX_RECONNECT_ATTEMPTS):
            try:
                if self._ws:
                    await self._ws.close()

                headers: dict[str, str] = {}
                if self._is_simulated:
                    headers["x-simulated-trading"] = "1"

                self._ws = await self._session.ws_connect(
                    self._endpoint,
                    headers=headers,
                    heartbeat=self.PING_INTERVAL,
                )

                await self._resubscribe_all()

                return

            except Exception:
                delay = self.RECONNECT_DELAYS[attempt]
                if attempt < self.MAX_RECONNECT_ATTEMPTS - 1:
                    await asyncio.sleep(delay)
                else:
                    self._running = False
                    sys.exit(1)

    async def _resubscribe_all(self) -> None:
        """重新订阅所有频道。"""
        for sub in self._subscriptions.values():
            await self._subscribe(sub)

    async def _subscribe(self, subscription: Subscription) -> None:
        """发送订阅请求。

        Args:
            subscription: 订阅信息
        """
        if not self._ws or self._ws.closed:
            return

        message = {
            "op": "subscribe",
            "args": [{"channel": subscription.channel, "instId": subscription.inst_id}],
        }
        await self._ws.send_str(json.dumps(message))

    async def subscribe_candles(
        self,
        inst_id: str,
        timeframe: str,
        callback: Callable[[KlineData], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """订阅K线频道。

        Args:
            inst_id: 交易对ID
            timeframe: K线周期，如 "1H", "4H"
            callback: K线数据回调函数
        """
        channel = f"candle{timeframe}"
        sub_key = f"{channel}:{inst_id}"

        async def kline_callback(data: Any) -> None:
            if callback and isinstance(data, list) and len(data) > 0:
                for item in data:
                    if isinstance(item, list) and len(item) >= 8:
                        kline = KlineData.from_ws_message(item, inst_id, timeframe)
                        await callback(kline)

        subscription = Subscription(
            channel=channel,
            inst_id=inst_id,
            callback=kline_callback,
        )
        self._subscriptions[sub_key] = subscription

        if self._ws and not self._ws.closed:
            await self._subscribe(subscription)

    async def unsubscribe(self, channel: str, inst_id: str) -> None:
        """取消订阅。

        Args:
            channel: 频道名称
            inst_id: 交易对ID
        """
        sub_key = f"{channel}:{inst_id}"
        if sub_key in self._subscriptions:
            del self._subscriptions[sub_key]

        if not self._ws or self._ws.closed:
            return

        message = {
            "op": "unsubscribe",
            "args": [{"channel": channel, "instId": inst_id}],
        }
        await self._ws.send_str(json.dumps(message))

    async def _ping_loop(self) -> None:
        """心跳发送循环。"""
        while self._running:
            try:
                await asyncio.sleep(self.PING_INTERVAL)
                if self._ws and not self._ws.closed:
                    await self._ws.send_str("ping")
            except asyncio.CancelledError:
                break
            except Exception:
                break

    async def _receive_loop(self) -> None:
        """消息接收循环。"""
        while self._running:
            try:
                if not self._ws or self._ws.closed:
                    await asyncio.sleep(1)
                    continue

                msg = await self._ws.receive()

                if msg.type == aiohttp.WSMsgType.TEXT:
                    text = msg.data
                    if text == "pong":
                        continue
                    await self._handle_message(text)

                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    await self._reconnect()

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    await self._reconnect()

            except asyncio.CancelledError:
                break
            except Exception:
                await self._reconnect()

    async def _handle_message(self, text: str) -> None:
        """处理收到的消息。

        Args:
            text: 消息文本
        """
        try:
            data = json.loads(text)

            if "event" in data:
                event = data.get("event")
                if event in ("subscribe", "unsubscribe", "error"):
                    return

            if "arg" in data and "data" in data:
                arg = data["arg"]
                channel = arg.get("channel", "")
                inst_id = arg.get("instId", "")
                msg_data = data["data"]

                sub_key = f"{channel}:{inst_id}"
                if sub_key in self._subscriptions:
                    sub = self._subscriptions[sub_key]
                    if sub.callback:
                        await sub.callback(msg_data)

                if self._message_handler:
                    await self._message_handler(channel, msg_data)

        except json.JSONDecodeError:
            pass

    async def close(self) -> None:
        """关闭WebSocket连接。"""
        self._running = False

        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
            self._ping_task = None

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        if self._session:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> OkxWebSocketClient:
        """异步上下文管理器入口。"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """异步上下文管理器退出。"""
        await self.close()
