"""K线绘图工具，生成PNG格式图片。"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

from src.infrastructure.logger import Logger

if TYPE_CHECKING:
    from numpy.typing import NDArray


@dataclass
class KlineData:
    """K线数据。"""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


class KlinePlotter:
    """K线绘图器，生成带EMA均线的K线图。"""

    RESOLUTION_1080P = (1920, 1080)
    DPI = 100

    COLOR_UP = "#000000"
    COLOR_DOWN = "#000000"
    COLOR_EMA = "#000000"

    def __init__(self) -> None:
        """初始化绘图器。"""
        self._logger = Logger()
        matplotlib.use("Agg")

    def plot(
        self,
        klines: list[KlineData],
        ema_values: NDArray[np.float64] | None = None,
    ) -> bytes:
        """生成K线图并返回PNG字节数据。

        Args:
            klines: K线数据列表
            ema_values: EMA值数组，可选

        Returns:
            PNG格式图片字节数据

        Raises:
            ValueError: 输入数据为空或格式错误
        """
        if not klines:
            raise ValueError("K线数据不能为空")

        width, height = self.RESOLUTION_1080P
        fig, ax = plt.subplots(figsize=(width / self.DPI, height / self.DPI), dpi=self.DPI)

        try:
            self._plot_candles(ax, klines)

            if ema_values is not None and len(ema_values) > 0:
                self._plot_ema(ax, klines, ema_values)

            self._setup_axes(ax, klines)

            ax.set_position([0.08, 0.12, 0.88, 0.82])

            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=self.DPI, facecolor="white", edgecolor="none")
            buf.seek(0)
            png_data = buf.getvalue()
            buf.close()

            self._logger.debug(f"K线图生成完成: {len(png_data)} bytes, {width}x{height}")
            return png_data

        finally:
            plt.close(fig)
            plt.clf()

    def plot_to_base64(
        self,
        klines: list[KlineData],
        ema_values: NDArray[np.float64] | None = None,
    ) -> str:
        """生成K线图并返回base64编码字符串。

        Args:
            klines: K线数据列表
            ema_values: EMA值数组，可选

        Returns:
            base64编码的PNG图片字符串
        """
        png_data = self.plot(klines, ema_values)
        return base64.b64encode(png_data).decode("utf-8")

    def save_to_file(
        self,
        filepath: str,
        klines: list[KlineData],
        ema_values: NDArray[np.float64] | None = None,
    ) -> None:
        """生成K线图并保存到文件（用于调试）。

        Args:
            filepath: 保存路径
            klines: K线数据列表
            ema_values: EMA值数组，可选
        """
        png_data = self.plot(klines, ema_values)
        with open(filepath, "wb") as f:
            f.write(png_data)
        self._logger.info(f"K线图已保存: {filepath}")

    def _plot_candles(self, ax: plt.Axes, klines: list[KlineData]) -> None:
        """绘制蜡烛图（黑白配色）。"""
        timestamps = [k.timestamp for k in klines]
        x_positions = range(len(klines))

        for i, kline in enumerate(klines):
            x = i
            is_up = kline.close >= kline.open

            # 影线：黑色
            ax.plot([x, x], [kline.low, kline.high], color="black", linewidth=1)

            height = abs(kline.close - kline.open)
            bottom = min(kline.open, kline.close)

            if is_up:
                # 阳线：白色实体，黑色边框
                rect = plt.Rectangle(
                    (x - 0.4, bottom),
                    0.8,
                    height if height > 0 else 0.01,
                    facecolor="white",
                    edgecolor="black",
                    linewidth=1,
                    zorder=3,
                )
            else:
                # 阴线：黑色实体，黑色边框
                rect = plt.Rectangle(
                    (x - 0.4, bottom),
                    0.8,
                    height if height > 0 else 0.01,
                    facecolor="black",
                    edgecolor="black",
                    linewidth=1,
                    zorder=3,
                )
            ax.add_patch(rect)

        ax.set_xlim(-0.5, len(klines) - 0.5)

    def _plot_ema(
        self,
        ax: plt.Axes,
        klines: list[KlineData],
        ema_values: NDArray[np.float64],
    ) -> None:
        """绘制EMA均线。"""
        x_positions = range(len(klines))

        valid_mask = ~np.isnan(ema_values)
        if np.any(valid_mask):
            valid_x = np.array(x_positions)[valid_mask]
            valid_ema = ema_values[valid_mask]
            ax.plot(valid_x, valid_ema, color=self.COLOR_EMA, linewidth=1.5, label="EMA20")

    def _setup_axes(self, ax: plt.Axes, klines: list[KlineData]) -> None:
        """设置坐标轴。"""
        timestamps = [k.timestamp for k in klines]

        ax.set_xlabel("Time", fontsize=12)
        ax.set_ylabel("Price", fontsize=12)

        tick_positions = []
        tick_labels = []

        n = len(klines)
        if n <= 10:
            step = 1
        elif n <= 30:
            step = 5
        elif n <= 60:
            step = 10
        else:
            step = max(1, n // 10)

        for i in range(0, n, step):
            tick_positions.append(i)
            tick_labels.append(timestamps[i].strftime("%m-%d %H:%M"))

        if n - 1 not in tick_positions:
            tick_positions.append(n - 1)
            tick_labels.append(timestamps[-1].strftime("%m-%d %H:%M"))

        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, rotation=0, ha="center", fontsize=10)

        prices = []
        for k in klines:
            prices.extend([k.open, k.high, k.low, k.close])

        min_price = min(prices)
        max_price = max(prices)
        price_range = max_price - min_price

        if price_range > 0:
            ax.set_ylim(min_price - price_range * 0.05, max_price + price_range * 0.05)

        ax.tick_params(axis='y', labelsize=11)

        ax.grid(True, linestyle="--", alpha=0.3)
        ax.legend(loc="upper left", fontsize=10)
