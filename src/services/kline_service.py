"""
K线服务
处理K线数据获取和图表生成
"""

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

    async def subscribe_kline(self, inst_id: str, timeframe: str, callback):
        """
        订阅K线频道

        Args:
            inst_id: 交易对ID
            timeframe: K线周期
            callback: K线收盘事件回调函数
        """
        channel = f"candle{timeframe}"

        async def ws_callback(data):
            """WebSocket消息回调"""
            for item in data:
                kline = Kline.from_okx_data(item)

                # 检查是否为收盘K线 (confirm=1)
                if kline.confirm == 1:
                    event = KlineCloseEvent(
                        inst_id=inst_id,
                        timeframe=timeframe,
                        kline=kline,
                    )
                    await callback(event)

        self.okx_ws_client.register_callback(channel, inst_id, ws_callback)
        await self.okx_ws_client.subscribe(channel, inst_id)
        self.logger.info(f"Subscribed to {channel} for {inst_id}")

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
