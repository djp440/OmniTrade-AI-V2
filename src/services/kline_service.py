"""K线服务

监听WebSocket K线收盘事件，获取K线数据，计算EMA20，生成K线图base64。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Coroutine

import numpy as np

from src.domain.events import KlineCloseEvent
from src.domain.trading import Kline
from src.infrastructure.ema_calculator import EMACalculator
from src.infrastructure.kline_plotter import KlineData, KlinePlotter
from src.infrastructure.logger import Logger

if TYPE_CHECKING:
    from decimal import Decimal

    from src.domain.config import TradePairConfig
    from src.infrastructure.okx_rest_client import OkxRestClient
    from src.infrastructure.okx_ws_client import OkxWebSocketClient


class KlineService:
    """K线服务

    负责监听K线收盘事件，获取历史K线数据，计算EMA20，生成K线图。
    """

    def __init__(
        self,
        rest_client: OkxRestClient,
        ws_client: OkxWebSocketClient,
        trade_pair_config: TradePairConfig,
        kline_count: int = 100,
    ) -> None:
        """初始化K线服务

        Args:
            rest_client: OKX REST客户端
            ws_client: OKX WebSocket客户端
            trade_pair_config: 交易对配置
            kline_count: 获取的历史K线数量
        """
        self._rest_client = rest_client
        self._ws_client = ws_client
        self._config = trade_pair_config
        self._kline_count = kline_count
        self._logger = Logger()
        self._plotter = KlinePlotter()
        self._ema_calculator = EMACalculator()
        self._kline_close_handlers: list[Callable[[KlineCloseEvent], Coroutine[Any, Any, None]]] = []

    def add_kline_close_handler(
        self,
        handler: Callable[[KlineCloseEvent], Coroutine[Any, Any, None]],
    ) -> None:
        """添加K线收盘事件处理器

        Args:
            handler: 事件处理函数
        """
        self._kline_close_handlers.append(handler)
        self._logger.debug(f"已添加K线收盘事件处理器: {self._config.inst_id}")

    async def start(self) -> None:
        """启动K线服务，订阅WebSocket频道"""
        await self._ws_client.subscribe_candles(
            inst_id=self._config.inst_id,
            timeframe=self._config.timeframe,
            callback=self._on_kline_received,
        )
        self._logger.info(f"K线服务已启动: {self._config.inst_id} {self._config.timeframe}")

    async def _on_kline_received(self, kline_data: "KlineData") -> None:
        """处理收到的K线数据

        Args:
            kline_data: K线数据
        """
        if kline_data.confirm != 1:
            return

        self._logger.info(
            f"收到K线收盘: {self._config.inst_id} "
            f"时间={kline_data.timestamp}, 收盘={kline_data.close}"
        )

        event = KlineCloseEvent(
            inst_id=self._config.inst_id,
            timeframe=self._config.timeframe,
            kline=Kline(
                timestamp=int(kline_data.timestamp),
                open=kline_data.open,
                high=kline_data.high,
                low=kline_data.low,
                close=kline_data.close,
                vol=kline_data.vol,
                confirm=kline_data.confirm,
            ),
        )

        for handler in self._kline_close_handlers:
            try:
                await handler(event)
            except Exception as e:
                self._logger.error(f"K线收盘事件处理失败: {e}")

    async def get_klines_with_ema(self) -> tuple[list[Kline], np.ndarray, str]:
        """获取K线数据，计算EMA20，生成K线图base64

        Returns:
            tuple: (K线列表, EMA20数组, K线图base64字符串)
        """
        klines = await self._fetch_klines()

        if len(klines) < 20:
            raise ValueError(f"K线数据不足，需要至少20根，当前: {len(klines)}")

        closes = np.array([float(k.close) for k in klines], dtype=np.float64)
        ema_values = self._ema_calculator.calculate_ema20(closes)

        kline_data_list = [
            KlineData(
                timestamp=datetime.fromtimestamp(k.timestamp / 1000),
                open=float(k.open),
                high=float(k.high),
                low=float(k.low),
                close=float(k.close),
            )
            for k in klines
        ]

        base64_image = self._plotter.plot_to_base64(kline_data_list, ema_values)

        self._logger.debug(
            f"K线数据获取完成: {self._config.inst_id}, "
            f"共{len(klines)}根K线, EMA20最新值={ema_values[-1]:.2f}"
        )

        return klines, ema_values, base64_image

    async def _fetch_klines(self) -> list[Kline]:
        """从OKX获取历史K线数据

        Returns:
            K线列表
        """
        response = await self._rest_client.get_candles(
            inst_id=self._config.inst_id,
            bar=self._config.timeframe,
            limit=self._kline_count,
        )

        data = response.get("data", [])
        klines: list[Kline] = []

        for item in data:
            try:
                kline = Kline.from_okx_data(item)
                klines.append(kline)
            except Exception as e:
                self._logger.warning(f"K线数据解析失败: {item}, 错误: {e}")

        klines.reverse()

        return klines

    async def get_current_price(self) -> Decimal:
        """获取当前价格（最新收盘价）

        Returns:
            当前价格
        """
        response = await self._rest_client.get_candles(
            inst_id=self._config.inst_id,
            bar=self._config.timeframe,
            limit=1,
        )

        data = response.get("data", [])
        if not data:
            raise ValueError("无法获取当前价格")

        from decimal import Decimal

        return Decimal(str(data[0][4]))
