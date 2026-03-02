"""OKX REST API客户端，基于aiohttp实现异步HTTP请求。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Literal

import aiohttp

from .okx_auth import OkxCredentials, OkxSigner


class OkxRestClient:
    """OKX REST API异步客户端。

    特性：
    - 连接池复用
    - 指数退避重试（最多3次，间隔1s/2s/4s）
    - 自动签名和请求头拼装
    - 支持实盘和模拟盘切换
    """

    REST_ENDPOINT = "https://www.okx.com"
    TIMEOUT_SECONDS = 10
    MAX_RETRIES = 3
    RETRY_DELAYS = [1, 2, 4]

    def __init__(
        self,
        credentials: OkxCredentials,
        is_simulated: bool = False,
    ) -> None:
        """初始化REST客户端。

        Args:
            credentials: OKX API凭证
            is_simulated: 是否使用模拟盘
        """
        self._credentials = credentials
        self._is_simulated = is_simulated
        self._signer = OkxSigner(credentials)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建HTTP会话（连接池复用）。"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.TIMEOUT_SECONDS)
            connector = aiohttp.TCPConnector(limit=100, limit_per_host=20)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
            )
        return self._session

    def _generate_timestamp(self) -> str:
        """生成ISO格式时间戳。"""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    async def _request_with_retry(
        self,
        method: Literal["GET", "POST", "PUT", "DELETE"],
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """带重试机制的HTTP请求。

        Args:
            method: HTTP方法
            path: API路径（不含域名）
            params: URL查询参数
            body: 请求体

        Returns:
            API响应数据

        Raises:
            OkxApiError: API调用失败时抛出
        """
        url = f"{self.REST_ENDPOINT}{path}"
        body_str = json.dumps(body) if body else ""
        timestamp = self._generate_timestamp()

        headers = self._signer.generate_headers(
            timestamp=timestamp,
            method=method,
            request_path=path,
            body=body_str,
            is_simulated=self._is_simulated,
        )

        last_error: Exception | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    data=body_str if body_str else None,
                ) as response:
                    response_text = await response.text()

                    if response.status != 200:
                        try:
                            response_data = json.loads(response_text)
                        except json.JSONDecodeError:
                            response_data = {"raw": response_text}
                        raise OkxApiError(
                            f"HTTP错误 {response.status}: {response_text}",
                            status_code=response.status,
                            response=response_data,
                        )

                    response_data = json.loads(response_text)

                    if response_data.get("code") != "0":
                        raise OkxApiError(
                            f"API错误 {response_data.get('code')}: {response_data.get('msg')}",
                            status_code=int(response_data.get("code", -1)),
                            response=response_data,
                        )

                    return response_data

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_DELAYS[attempt]
                    await asyncio.sleep(delay)
                continue
            except json.JSONDecodeError as e:
                raise OkxApiError(f"JSON解析错误: {e}") from e

        raise OkxApiError(f"请求失败，已重试{self.MAX_RETRIES}次: {last_error}") from last_error

    async def close(self) -> None:
        """关闭HTTP会话。"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> OkxRestClient:
        """异步上下文管理器入口。"""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """异步上下文管理器退出。"""
        await self.close()

    # ==================== 账户类接口 ====================

    async def get_balance(self, ccy: str | None = None) -> dict[str, Any]:
        """查询账户余额。

        Args:
            ccy: 币种，如 "BTC"，不传返回所有币种

        Returns:
            余额数据
        """
        params = {"ccy": ccy} if ccy else {}
        return await self._request_with_retry("GET", "/api/v5/account/balance", params=params)

    async def get_positions(
        self,
        inst_type: str = "SWAP",
        inst_id: str | None = None,
    ) -> dict[str, Any]:
        """查询持仓信息。

        Args:
            inst_type: 产品类型，默认SWAP（永续合约）
            inst_id: 交易对ID，不传返回所有持仓

        Returns:
            持仓数据
        """
        params: dict[str, Any] = {"instType": inst_type}
        if inst_id:
            params["instId"] = inst_id
        return await self._request_with_retry("GET", "/api/v5/account/positions", params=params)

    async def set_position_mode(self, pos_mode: Literal["long_short_mode", "net_mode"]) -> dict[str, Any]:
        """设置持仓模式。

        Args:
            pos_mode: 持仓模式，long_short_mode（双向持仓）或 net_mode（单向持仓）

        Returns:
            设置结果
        """
        body = {"posMode": pos_mode}
        return await self._request_with_retry("POST", "/api/v5/account/set-position-mode", body=body)

    async def set_leverage(
        self,
        inst_id: str,
        lever: int,
        mgn_mode: Literal["isolated", "cross"] = "isolated",
        pos_side: Literal["long", "short"] | None = None,
    ) -> dict[str, Any]:
        """设置杠杆倍数。

        Args:
            inst_id: 交易对ID
            lever: 杠杆倍数
            mgn_mode: 保证金模式，isolated（逐仓）或 cross（全仓）
            pos_side: 持仓方向，双向持仓时必填

        Returns:
            设置结果
        """
        body: dict[str, Any] = {
            "instId": inst_id,
            "lever": str(lever),
            "mgnMode": mgn_mode,
        }
        if pos_side:
            body["posSide"] = pos_side
        return await self._request_with_retry("POST", "/api/v5/account/set-leverage", body=body)

    async def get_instrument(self, inst_id: str) -> dict[str, Any]:
        """查询交易对信息。

        Args:
            inst_id: 交易对ID

        Returns:
            交易对信息
        """
        params = {"instId": inst_id}
        return await self._request_with_retry("GET", "/api/v5/public/instruments", params=params)

    # ==================== 交易类接口 ====================

    async def place_order(
        self,
        inst_id: str,
        side: Literal["buy", "sell"],
        sz: str,
        ord_type: Literal["market", "limit"] = "market",
        td_mode: Literal["cross", "isolated"] = "isolated",
        pos_side: Literal["long", "short"] | None = None,
        attach_algo_ords: list[dict[str, Any]] | None = None,
        client_oid: str | None = None,
    ) -> dict[str, Any]:
        """下单。

        Args:
            inst_id: 交易对ID
            side: 买卖方向
            sz: 下单数量
            ord_type: 订单类型，market（市价）或 limit（限价）
            td_mode: 交易模式
            pos_side: 持仓方向，双向持仓时必填
            attach_algo_ords: 附带止盈止损条件单
            client_oid: 客户自定义订单ID（幂等）

        Returns:
            下单结果
        """
        body: dict[str, Any] = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": side,
            "ordType": ord_type,
            "sz": sz,
        }
        if pos_side:
            body["posSide"] = pos_side
        if client_oid:
            body["clOrdId"] = client_oid
        if attach_algo_ords:
            body["attachAlgoOrds"] = attach_algo_ords

        return await self._request_with_retry("POST", "/api/v5/trade/order", body=body)

    async def amend_order(
        self,
        inst_id: str,
        ord_id: str | None = None,
        client_oid: str | None = None,
        new_sz: str | None = None,
        new_px: str | None = None,
    ) -> dict[str, Any]:
        """修改订单。

        Args:
            inst_id: 交易对ID
            ord_id: 订单ID（ordId和client_oid至少填一个）
            client_oid: 客户自定义订单ID
            new_sz: 新数量
            new_px: 新价格

        Returns:
            修改结果
        """
        body: dict[str, Any] = {"instId": inst_id}
        if ord_id:
            body["ordId"] = ord_id
        if client_oid:
            body["clOrdId"] = client_oid
        if new_sz:
            body["newSz"] = new_sz
        if new_px:
            body["newPx"] = new_px

        return await self._request_with_retry("POST", "/api/v5/trade/amend-order", body=body)

    async def close_position(
        self,
        inst_id: str,
        pos_side: Literal["long", "short"] | None = None,
        mgn_mode: Literal["cross", "isolated"] = "isolated",
        auto_cxl: bool = True,
    ) -> dict[str, Any]:
        """平仓。

        Args:
            inst_id: 交易对ID
            pos_side: 持仓方向，双向持仓时必填
            mgn_mode: 保证金模式
            auto_cxl: 是否自动撤销关联的止盈止损订单

        Returns:
            平仓结果
        """
        body: dict[str, Any] = {
            "instId": inst_id,
            "mgnMode": mgn_mode,
            "autoCxl": auto_cxl,
        }
        if pos_side:
            body["posSide"] = pos_side

        return await self._request_with_retry("POST", "/api/v5/trade/close-position", body=body)

    async def get_order_info(
        self,
        inst_id: str,
        ord_id: str | None = None,
        client_oid: str | None = None,
    ) -> dict[str, Any]:
        """查询订单详情。

        Args:
            inst_id: 交易对ID
            ord_id: 订单ID（ordId和client_oid至少填一个）
            client_oid: 客户自定义订单ID

        Returns:
            订单详情
        """
        params: dict[str, Any] = {"instId": inst_id}
        if ord_id:
            params["ordId"] = ord_id
        if client_oid:
            params["clOrdId"] = client_oid

        return await self._request_with_retry("GET", "/api/v5/trade/order", params=params)

    # ==================== 行情类接口 ====================

    async def get_candles(
        self,
        inst_id: str,
        bar: str,
        limit: int = 100,
        after: str | None = None,
        before: str | None = None,
    ) -> dict[str, Any]:
        """查询历史K线数据。

        Args:
            inst_id: 交易对ID
            bar: K线周期，如 "1H", "4H", "1D"
            limit: 返回条数，最大300
            after: 以此时间戳之前的数据开始
            before: 以此时间戳之后的数据结束

        Returns:
            K线数据
        """
        params: dict[str, Any] = {
            "instId": inst_id,
            "bar": bar,
            "limit": min(limit, 300),
        }
        if after:
            params["after"] = after
        if before:
            params["before"] = before

        return await self._request_with_retry("GET", "/api/v5/market/candles", params=params)


class OkxApiError(Exception):
    """OKX API错误异常。"""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        """初始化异常。

        Args:
            message: 错误信息
            status_code: HTTP状态码或API错误码
            response: 完整响应数据
        """
        super().__init__(message)
        self.status_code = status_code
        self.response = response or {}
