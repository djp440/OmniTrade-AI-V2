"""EMA计算工具，基于numpy向量化运算。"""

from __future__ import annotations

import numpy as np


class EMACalculator:
    """EMA计算器，支持标准EMA计算。"""

    @staticmethod
    def calculate(closes: np.ndarray, period: int = 20) -> np.ndarray:
        """计算标准EMA。

        使用平滑系数: 2/(period+1)

        Args:
            closes: 收盘价数组，一维numpy数组
            period: EMA周期，默认20

        Returns:
            EMA值数组，与输入数组等长
            前period-1个值为NaN（因为无法计算有效EMA）

        Raises:
            ValueError: 输入数据不足或格式错误
        """
        if not isinstance(closes, np.ndarray):
            closes = np.array(closes, dtype=np.float64)
        else:
            closes = closes.astype(np.float64)

        if closes.ndim != 1:
            raise ValueError(f"收盘价必须是一维数组，当前维度: {closes.ndim}")

        if len(closes) < period:
            raise ValueError(f"数据点不足，需要至少{period}个数据点，当前: {len(closes)}")

        if period <= 0:
            raise ValueError(f"周期必须大于0，当前: {period}")

        alpha = 2.0 / (period + 1.0)

        ema = np.zeros_like(closes, dtype=np.float64)
        ema[:period - 1] = np.nan

        sma = np.mean(closes[:period])
        ema[period - 1] = sma

        for i in range(period, len(closes)):
            ema[i] = alpha * closes[i] + (1 - alpha) * ema[i - 1]

        return ema

    @staticmethod
    def calculate_ema20(closes: np.ndarray) -> np.ndarray:
        """计算EMA20。

        Args:
            closes: 收盘价数组

        Returns:
            EMA20值数组
        """
        return EMACalculator.calculate(closes, period=20)

    @staticmethod
    def get_last_valid_ema(ema_values: np.ndarray) -> float | None:
        """获取最后一个有效的EMA值。

        Args:
            ema_values: EMA值数组（可能包含NaN）

        Returns:
            最后一个有效EMA值，如果没有则返回None
        """
        valid_values = ema_values[~np.isnan(ema_values)]
        if len(valid_values) == 0:
            return None
        return float(valid_values[-1])
