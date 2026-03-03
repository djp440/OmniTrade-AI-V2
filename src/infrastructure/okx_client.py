"""
OKX客户端封装
基于aiohttp自主实现，禁止使用第三方OKX SDK
"""

import asyncio
import base64
import hashlib
import hmac
import json
import time
from typing import Any, Optional
from urllib.parse import urlencode

import aiohttp
import websockets


class OKXRestClient:
    """OKX REST API客户端"""

    REST_URL = "https://www.okx.com"
    TIMEOUT = 10
    MAX_RETRIES = 3

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str,
        demo_mode: bool = False,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.demo_mode = demo_mode
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def _generate_signature(
        self, timestamp: str, method: str, request_path: str, body: str = ""
    ) -> str:
        message = timestamp + method.upper() + request_path + body
        mac = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode("utf-8")

    def _get_headers(self, method: str, request_path: str, body: str = "") -> dict:
        timestamp = self._get_timestamp()
        signature = self._generate_signature(timestamp, method, request_path, body)

        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

        if self.demo_mode:
            headers["x-simulated-trading"] = "1"

        return headers

    def _get_timestamp(self) -> str:
        """获取ISO 8601格式的时间戳"""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        body: Optional[dict] = None,
    ) -> dict:
        session = await self._get_session()

        request_path = path
        if params:
            request_path = path + "?" + urlencode(params)

        body_str = ""
        if body:
            body_str = json.dumps(body)

        headers = self._get_headers(method, request_path, body_str)
        url = self.REST_URL + request_path

        for attempt in range(self.MAX_RETRIES):
            try:
                async with session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    data=body_str if body else None,
                    timeout=aiohttp.ClientTimeout(total=self.TIMEOUT),
                ) as response:
                    data = await response.json()

                    if data.get("code") != "0":
                        raise OKXAPIError(
                            f"OKX API error: {data.get('msg')} (code: {data.get('code')})"
                        )

                    return data.get("data", [])

            except asyncio.TimeoutError:
                if attempt == self.MAX_RETRIES - 1:
                    raise OKXAPIError(f"Request timeout after {self.MAX_RETRIES} retries")
                wait_time = 2**attempt
                await asyncio.sleep(wait_time)

            except Exception as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise OKXAPIError(f"Request failed: {str(e)}")
                wait_time = 2**attempt
                await asyncio.sleep(wait_time)

        return []

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    # ========== 账户类接口 ==========

    async def get_balance(self, ccy: str = "USDT") -> dict:
        """查询账户余额"""
        params = {"ccy": ccy}
        result = await self._request("GET", "/api/v5/account/balance", params=params)
        return result[0] if result else {}

    async def get_positions(self, inst_id: Optional[str] = None) -> list:
        """查询持仓信息"""
        params = {}
        if inst_id:
            params["instId"] = inst_id
        return await self._request("GET", "/api/v5/account/positions", params=params)

    async def set_position_mode(self, pos_mode: str = "net") -> dict:
        """设置持仓模式 (net: 单向持仓, long_short: 双向持仓)"""
        body = {"posMode": pos_mode}
        result = await self._request("POST", "/api/v5/account/set-position-mode", body=body)
        return result[0] if result else {}

    async def set_leverage(
        self,
        inst_id: str,
        lever: int,
        mgn_mode: str = "isolated",
        pos_side: Optional[str] = None,
    ) -> dict:
        """设置杠杆"""
        body = {"instId": inst_id, "lever": str(lever), "mgnMode": mgn_mode}
        if pos_side:
            body["posSide"] = pos_side
        result = await self._request("POST", "/api/v5/account/set-leverage", body=body)
        return result[0] if result else {}

    async def get_instrument_info(self, inst_id: str, inst_type: str = "SWAP") -> dict:
        """查询交易对信息"""
        params = {"instId": inst_id, "instType": inst_type}
        result = await self._request("GET", "/api/v5/public/instruments", params=params)
        return result[0] if result else {}

    # ========== 交易类接口 ==========

    async def place_order(
        self,
        inst_id: str,
        td_mode: str,
        side: str,
        ord_type: str,
        sz: str,
        px: Optional[str] = None,
        pos_side: Optional[str] = None,
        attach_algo_ords: Optional[list] = None,
        client_oid: Optional[str] = None,
    ) -> dict:
        """下单"""
        body = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": side,
            "ordType": ord_type,
            "sz": sz,
        }

        if px:
            body["px"] = px
        if pos_side:
            body["posSide"] = pos_side
        if attach_algo_ords:
            body["attachAlgoOrds"] = attach_algo_ords
        if client_oid:
            body["clOrdId"] = client_oid

        result = await self._request("POST", "/api/v5/trade/order", body=body)
        return result[0] if result else {}

    async def amend_order(
        self,
        inst_id: str,
        ord_id: Optional[str] = None,
        client_oid: Optional[str] = None,
        new_sz: Optional[str] = None,
        new_px: Optional[str] = None,
    ) -> dict:
        """修改订单"""
        body = {"instId": inst_id}

        if ord_id:
            body["ordId"] = ord_id
        if client_oid:
            body["clOrdId"] = client_oid
        if new_sz:
            body["newSz"] = new_sz
        if new_px:
            body["newPx"] = new_px

        result = await self._request("POST", "/api/v5/trade/amend-order", body=body)
        return result[0] if result else {}

    async def close_position(
        self,
        inst_id: str,
        pos_side: Optional[str] = None,
        mgn_mode: str = "isolated",
    ) -> dict:
        """平仓"""
        body = {"instId": inst_id, "mgnMode": mgn_mode}
        if pos_side:
            body["posSide"] = pos_side

        result = await self._request("POST", "/api/v5/trade/close-position", body=body)
        return result[0] if result else {}

    async def get_order_info(
        self,
        inst_id: str,
        ord_id: Optional[str] = None,
        client_oid: Optional[str] = None,
    ) -> dict:
        """查询订单详情"""
        params = {"instId": inst_id}
        if ord_id:
            params["ordId"] = ord_id
        if client_oid:
            params["clOrdId"] = client_oid

        result = await self._request("GET", "/api/v5/trade/order", params=params)
        return result[0] if result else {}

    async def cancel_order(
        self,
        inst_id: str,
        ord_id: Optional[str] = None,
        client_oid: Optional[str] = None,
    ) -> dict:
        """取消订单"""
        body = {"instId": inst_id}
        if ord_id:
            body["ordId"] = ord_id
        if client_oid:
            body["clOrdId"] = client_oid

        result = await self._request("POST", "/api/v5/trade/cancel-order", body=body)
        return result[0] if result else {}

    # ========== 行情类接口 ==========

    async def get_candlesticks(
        self,
        inst_id: str,
        bar: str = "1H",
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> list:
        """获取历史K线数据"""
        params = {"instId": inst_id, "bar": bar, "limit": str(limit)}
        if after:
            params["after"] = after
        if before:
            params["before"] = before

        return await self._request("GET", "/api/v5/market/candles", params=params)


class OKXWebSocketClient:
    """OKX WebSocket客户端"""

    # OKX WebSocket公共频道URL (根据官方文档)
    WS_PUBLIC_URL = "wss://ws.okx.com:8443/ws/v5/public"
    # 模拟盘WebSocket URL (模拟盘不支持WebSocket公共频道，使用实盘获取K线数据)
    WS_PUBLIC_DEMO_URL = "wss://ws.okx.com:8443/ws/v5/public"
    MAX_RECONNECT_ATTEMPTS = 5

    def __init__(self, demo_mode: bool = False):
        self.demo_mode = demo_mode
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.subscriptions: set = set()
        self.callbacks: dict = {}
        self.running = False
        self.reconnect_count = 0
        self._connect_lock = asyncio.Lock()  # 添加连接锁

    async def connect(self):
        """建立WebSocket连接（线程安全）"""
        async with self._connect_lock:
            # 如果已经连接，直接返回
            if self._is_ws_connected():
                print(f"[WebSocket] Already connected, reusing existing connection")
                return

            # K线数据使用实盘WebSocket（公共数据），模拟盘可能不支持K线频道
            # 注意：交易操作仍然使用模拟盘REST API
            url = self.WS_PUBLIC_URL
            print(f"[WebSocket] Connecting to {url}...")

            for attempt in range(self.MAX_RECONNECT_ATTEMPTS):
                try:
                    self.ws = await websockets.connect(url)
                    self.reconnect_count = 0
                    self.running = True
                    print(f"[WebSocket] Connected successfully, type: {type(self.ws)}")

                    # 重新订阅之前的频道
                    for channel, inst_id in self.subscriptions:
                        await self.subscribe(channel, inst_id)

                    return

                except Exception as e:
                    print(f"[WebSocket] Connection attempt {attempt + 1} failed: {e}")
                    self.reconnect_count += 1
                    if self.reconnect_count >= self.MAX_RECONNECT_ATTEMPTS:
                        raise OKXWebSocketError(
                            f"WebSocket reconnection failed after {self.MAX_RECONNECT_ATTEMPTS} attempts: {e}"
                        )

                    wait_time = 2 ** (self.reconnect_count - 1)
                    await asyncio.sleep(wait_time)

    def _is_ws_connected(self) -> bool:
        """检查WebSocket是否已连接"""
        if self.ws is None:
            return False
        # 兼容websockets和aiohttp的WebSocket对象
        if hasattr(self.ws, 'open'):
            return self.ws.open
        elif hasattr(self.ws, 'closed'):
            return not self.ws.closed
        elif hasattr(self.ws, 'state'):
            # websockets 14+ 使用state属性
            from websockets.protocol import State
            return self.ws.state == State.OPEN
        else:
            # 对于aiohttp的ClientWebSocketResponse，使用_close_code属性
            return not getattr(self.ws, '_closed', True)

    def _get_ws_state(self) -> dict:
        """获取WebSocket状态信息（用于调试）"""
        if self.ws is None:
            return {"ws": None}
        return {
            "type": type(self.ws).__name__,
            "has_open": hasattr(self.ws, 'open'),
            "has_closed": hasattr(self.ws, 'closed'),
            "has__closed": hasattr(self.ws, '_closed'),
            "open": getattr(self.ws, 'open', 'N/A'),
            "closed": getattr(self.ws, 'closed', 'N/A'),
            "_closed": getattr(self.ws, '_closed', 'N/A'),
        }

    async def subscribe(self, channel: str, inst_id: str):
        """订阅频道"""
        if not self._is_ws_connected():
            state = self._get_ws_state()
            print(f"[WebSocket] Connection check failed. State: {state}")
            raise OKXWebSocketError("WebSocket not connected")

        sub_message = {
            "op": "subscribe",
            "args": [{"channel": channel, "instId": inst_id}],
        }
        await self.ws.send(json.dumps(sub_message))
        self.subscriptions.add((channel, inst_id))

    async def unsubscribe(self, channel: str, inst_id: str):
        """取消订阅频道"""
        if not self._is_ws_connected():
            return

        unsub_message = {
            "op": "unsubscribe",
            "args": [{"channel": channel, "instId": inst_id}],
        }

        await self.ws.send(json.dumps(unsub_message))
        self.subscriptions.discard((channel, inst_id))

    async def listen(self, callback):
        """监听WebSocket消息"""
        while self.running:
            try:
                if not self._is_ws_connected():
                    await self.connect()

                message = await self.ws.recv()
                data = json.loads(message)

                # 处理心跳
                if data.get("event") == "ping":
                    await self.ws.send(json.dumps({"op": "pong"}))
                    continue

                # 处理订阅确认
                if data.get("event") in ["subscribe", "error"]:
                    continue

                # 处理数据推送
                if "data" in data:
                    channel = data.get("arg", {}).get("channel")
                    inst_id = data.get("arg", {}).get("instId")
                    key = (channel, inst_id)

                    if key in self.callbacks:
                        await self.callbacks[key](data["data"])
                    else:
                        await callback(data)

            except websockets.exceptions.ConnectionClosed:
                if self.running:
                    await self.connect()
            except Exception as e:
                if self.running:
                    await asyncio.sleep(1)

    def register_callback(self, channel: str, inst_id: str, callback):
        """注册特定频道的回调函数"""
        self.callbacks[(channel, inst_id)] = callback

    async def close(self):
        """关闭WebSocket连接"""
        self.running = False
        if self.ws:
            try:
                await self.ws.close()
            except Exception as e:
                pass  # 忽略关闭时的错误


class OKXAPIError(Exception):
    """OKX API错误"""
    pass


class OKXWebSocketError(Exception):
    """OKX WebSocket错误"""
    pass
