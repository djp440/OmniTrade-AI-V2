"""
K线服务
处理K线数据获取和图表生成
"""

import asyncio
import time
from datetime import datetime, timezone

from src.domain.models import Kline, KlineCloseEvent
from src.infrastructure.logger import Logger
from src.infrastructure.okx_client import OKXRestClient, OKXWebSocketClient
from src.infrastructure.utils import calculate_ema, generate_kline_chart


class KlineService:
    """K线服务"""

    def __init__(
        self,
        okx_rest_client: OKXRestClient,
        okx_ws_client: OKXWebSocketClient,
        logger: Logger,
    ):
        self.okx_rest_client = okx_rest_client
        self.okx_ws_client = okx_ws_client
        self.logger = logger

    def _get_timeframe_seconds(self, timeframe: str) -> int:
        """将K线周期转换为秒数"""
        timeframe_map = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "1H": 3600,
            "4H": 14400,
            "1D": 86400,
        }
        return timeframe_map.get(timeframe, 300)

    def _get_next_close_timestamp(self, last_kline_open_ms: int, timeframe: str) -> int:
        """
        计算下一根K线的收盘时间戳（毫秒）

        注意：OKX返回的K线时间戳是开盘时间。
        例如：5m K线 19:30:00 开盘，19:35:00 收盘

        Args:
            last_kline_open_ms: 上一根K线的开盘时间戳（毫秒）
            timeframe: K线周期

        Returns:
            下一根K线收盘时间戳（毫秒）
        """
        timeframe_seconds = self._get_timeframe_seconds(timeframe)
        # 下一根K线开盘时间 = 上一根开盘时间 + 周期
        # 下一根K线收盘时间 = 下一根开盘时间 + 周期 = 上一根开盘时间 + 2 * 周期
        return last_kline_open_ms + 2 * timeframe_seconds * 1000

    def _sleep_until_next_close(self, next_close_ms: int) -> float:
        """
        计算需要睡眠的秒数，直到下一根K线收盘

        Args:
            next_close_ms: 下一根K线收盘时间戳（毫秒）

        Returns:
            需要睡眠的秒数
        """
        current_ms = int(time.time() * 1000)
        sleep_ms = next_close_ms - current_ms
        # 提前1秒唤醒，确保能准时检测到
        sleep_seconds = max(0, (sleep_ms / 1000) - 1)
        return sleep_seconds

    async def subscribe_kline(self, inst_id: str, timeframe: str, callback):
        """
        订阅K线频道（使用基于系统时间的精确触发）

        策略：
        1. 获取当前最新的收盘K线时间戳
        2. 计算下一根K线的收盘时间
        3. 睡眠到下一根K线收盘前1秒
        4. 在收盘时刻附近轮询检测，直到检测到新的收盘K线
        5. 重复步骤2-4

        Args:
            inst_id: 交易对ID
            timeframe: K线周期
            callback: K线收盘事件回调函数
        """
        self.logger.info(
            f"Starting precise Kline monitoring for {inst_id} with timeframe {timeframe}"
        )

        # 初始化：获取当前最新的收盘K线
        try:
            klines = await self.get_historical_klines(
                inst_id=inst_id,
                timeframe=timeframe,
                limit=2,
            )
            if len(klines) >= 2:
                last_closed_kline = klines[-2]
                last_closed_timestamp = last_closed_kline.timestamp
                self.logger.info(
                    f"Initialized monitoring for {inst_id}, "
                    f"last closed kline: {datetime.fromtimestamp(last_closed_timestamp / 1000)}"
                )
            else:
                self.logger.error(f"Failed to get initial klines for {inst_id}")
                return
        except Exception as e:
            self.logger.error(f"Failed to initialize monitoring for {inst_id}: {e}")
            return

        while True:
            try:
                # 计算下一根K线的收盘时间
                # last_closed_timestamp 是上一根已收盘K线的开盘时间
                next_close_timestamp = self._get_next_close_timestamp(
                    last_closed_timestamp, timeframe
                )
                next_close_dt = datetime.fromtimestamp(next_close_timestamp / 1000)
                current_dt = datetime.now()
                wait_seconds = (next_close_dt - current_dt).total_seconds()

                self.logger.info(
                    f"Next kline close for {inst_id} at {next_close_dt} "
                    f"(in {wait_seconds:.0f}s), waiting..."
                )

                # 睡眠到下一根K线收盘前1秒
                sleep_seconds = self._sleep_until_next_close(next_close_timestamp)
                if sleep_seconds > 0:
                    self.logger.debug(f"Sleeping for {sleep_seconds:.1f} seconds...")
                    await asyncio.sleep(sleep_seconds)

                # 在收盘时刻附近密集轮询，直到检测到新的收盘K线
                # 最多轮询30秒（考虑网络延迟和交易所数据更新延迟）
                max_wait_seconds = 30
                poll_interval = 0.5  # 每500毫秒检查一次
                waited_seconds = 0

                while waited_seconds < max_wait_seconds:
                    # 获取最新的K线数据
                    klines = await self.get_historical_klines(
                        inst_id=inst_id,
                        timeframe=timeframe,
                        limit=2,
                    )

                    if len(klines) >= 2:
                        latest_closed_kline = klines[-2]

                        # 检查是否检测到新的收盘K线
                        if latest_closed_kline.timestamp > last_closed_timestamp:
                            close_dt = datetime.fromtimestamp(
                                latest_closed_kline.timestamp / 1000
                            )
                            self.logger.info(
                                f"Kline CLOSED for {inst_id} at {close_dt}, "
                                f"triggering analysis..."
                            )

                            event = KlineCloseEvent(
                                inst_id=inst_id,
                                timeframe=timeframe,
                                kline=latest_closed_kline,
                            )
                            await callback(event)

                            last_closed_timestamp = latest_closed_kline.timestamp
                            break  # 检测到收盘，跳出轮询循环

                    # 未检测到，继续等待
                    await asyncio.sleep(poll_interval)
                    waited_seconds += poll_interval

                else:
                    # 超时未检测到新的收盘K线
                    self.logger.warning(
                        f"Timeout waiting for kline close for {inst_id}, "
                        f"expected at {next_close_dt}"
                    )

            except Exception as e:
                self.logger.error(f"Error in kline monitoring for {inst_id}: {e}")
                await asyncio.sleep(5)  # 出错后等待5秒再重试

    async def get_historical_klines(
        self, inst_id: str, timeframe: str, limit: int
    ) -> list[Kline]:
        """
        获取历史K线数据

        Args:
            inst_id: 交易对ID
            timeframe: K线周期
            limit: 获取数量

        Returns:
            K线数据列表
        """
        raw_data = await self.okx_rest_client.get_candlesticks(
            inst_id=inst_id,
            bar=timeframe,
            limit=limit,
        )

        klines = [Kline.from_okx_data(item) for item in raw_data]
        # 按时间戳排序
        klines.sort(key=lambda x: x.timestamp)

        self.logger.debug(f"Fetched {len(klines)} klines for {inst_id}")
        return klines

    def calculate_ema(self, klines: list[Kline], period: int = 20) -> list[float]:
        """
        计算EMA

        Args:
            klines: K线数据列表
            period: EMA周期

        Returns:
            EMA值列表
        """
        closes = [k.close for k in klines]
        return calculate_ema(closes, period)

    def generate_chart(
        self,
        klines: list[Kline],
        ema_values: list[float],
        inst_id: str,
        timeframe: str,
        save_path: str = None,
    ) -> str:
        """
        生成K线图

        Args:
            klines: K线数据列表
            ema_values: EMA值列表
            inst_id: 交易对ID
            timeframe: K线周期
            save_path: 保存路径（可选）

        Returns:
            base64编码的图片字符串
        """
        # 转换K线为字典格式
        kline_dicts = [
            {
                "timestamp": k.timestamp,
                "open": k.open,
                "high": k.high,
                "low": k.low,
                "close": k.close,
            }
            for k in klines
        ]

        img_base64 = generate_kline_chart(
            klines=kline_dicts,
            ema_values=ema_values,
            inst_id=inst_id,
            timeframe=timeframe,
            save_path=save_path,
        )

        self.logger.debug(f"Generated chart for {inst_id}")
        return img_base64
