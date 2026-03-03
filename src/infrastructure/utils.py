"""
工具组件
包含EMA计算、K线绘图、CSV操作等功能
"""

import base64
import csv
import io
import os
from datetime import datetime
from typing import Optional

import numpy as np
from matplotlib import font_manager as fm
from matplotlib import pyplot as plt


def calculate_ema(prices: list[float], period: int = 20) -> list[float]:
    """
    计算EMA（指数移动平均线）

    Args:
        prices: 收盘价列表
        period: EMA周期，默认20

    Returns:
        EMA值列表
    """
    if len(prices) < period:
        return []

    multiplier = 2 / (period + 1)
    ema_values = []

    # 第一个EMA值使用SMA
    sma = sum(prices[:period]) / period
    ema_values.append(sma)

    # 计算后续EMA值
    for price in prices[period:]:
        ema = (price - ema_values[-1]) * multiplier + ema_values[-1]
        ema_values.append(ema)

    return ema_values


def generate_kline_chart(
    klines: list[dict],
    ema_values: list[float],
    inst_id: str,
    timeframe: str,
    save_path: Optional[str] = None,
) -> str:
    """
    生成K线图

    Args:
        klines: K线数据列表，每个元素包含timestamp, open, high, low, close
        ema_values: EMA值列表
        inst_id: 交易对ID
        timeframe: K线周期
        save_path: 保存路径，如果为None则只返回base64

    Returns:
        base64编码的图片字符串
    """
    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

    fig, ax = plt.subplots(figsize=(12, 6), dpi=100)

    # 准备数据
    timestamps = []
    opens = []
    highs = []
    lows = []
    closes = []

    for k in klines:
        timestamps.append(datetime.fromtimestamp(int(k["timestamp"]) / 1000))
        opens.append(float(k["open"]))
        highs.append(float(k["high"]))
        lows.append(float(k["low"]))
        closes.append(float(k["close"]))

    # 绘制K线
    for i, (ts, o, h, l, c) in enumerate(zip(timestamps, opens, highs, lows, closes)):
        color = "black" if c >= o else "black"
        fill_color = "white" if c >= o else "black"

        # 影线
        ax.plot([i, i], [l, h], color="black", linewidth=0.8)

        # 实体
        height = abs(c - o)
        bottom = min(o, c)
        rect = plt.Rectangle(
            (i - 0.4, bottom),
            0.8,
            height if height > 0 else 0.01,
            facecolor=fill_color,
            edgecolor="black",
            linewidth=0.8,
        )
        ax.add_patch(rect)

    # 绘制EMA20
    if ema_values and len(ema_values) == len(klines):
        x_values = range(len(klines))
        ax.plot(x_values, ema_values, color="blue", linewidth=1.5, label="EMA20")

    # 设置标题和标签
    ax.set_title(f"{inst_id} - {timeframe}", fontsize=14, fontweight="bold")
    ax.set_xlabel("Time", fontsize=10)
    ax.set_ylabel("Price", fontsize=10)

    # 设置x轴刻度
    n_ticks = min(10, len(timestamps))
    tick_indices = np.linspace(0, len(timestamps) - 1, n_ticks, dtype=int)
    tick_labels = [timestamps[i].strftime("%Y-%m-%d %H:%M") for i in tick_indices]
    ax.set_xticks(tick_indices)
    ax.set_xticklabels(tick_labels, rotation=45, ha="right")

    # 添加图例
    ax.legend(loc="upper left")

    # 调整布局
    plt.tight_layout()

    # 保存到内存
    buffer = io.BytesIO()
    plt.savefig(buffer, format="png", facecolor="white")
    buffer.seek(0)

    # 转换为base64
    img_base64 = base64.b64encode(buffer.read()).decode("utf-8")

    # 保存到文件（如果指定了路径）
    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        buffer.seek(0)
        with open(save_path, "wb") as f:
            f.write(buffer.read())

    # 清理
    plt.close(fig)
    buffer.close()

    return img_base64


class TradeRecordStorage:
    """交易记录存储"""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        """确保文件存在，如果不存在则创建并写入表头"""
        if not os.path.exists(self.file_path):
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp",
                    "inst_id",
                    "position_direction",
                    "position_size",
                    "entry_avg_price",
                    "exit_avg_price",
                    "realized_pnl",
                    "balance_after_close",
                    "order_id",
                ])

    def append_record(self, record: dict):
        """
        追加交易记录

        Args:
            record: 交易记录字典
        """
        with open(self.file_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                record.get("timestamp", ""),
                record.get("inst_id", ""),
                record.get("position_direction", ""),
                record.get("position_size", ""),
                record.get("entry_avg_price", ""),
                record.get("exit_avg_price", ""),
                record.get("realized_pnl", ""),
                record.get("balance_after_close", ""),
                record.get("order_id", ""),
            ])

    def read_all_records(self) -> list[dict]:
        """读取所有交易记录"""
        records = []
        if not os.path.exists(self.file_path):
            return records

        with open(self.file_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(dict(row))

        return records


def parse_kline_data(raw_data: list) -> list[dict]:
    """
    解析OKX返回的K线数据

    Args:
        raw_data: OKX API返回的原始K线数据

    Returns:
        解析后的K线数据列表
    """
    klines = []
    for item in raw_data:
        klines.append({
            "timestamp": int(item[0]),
            "open": item[1],
            "high": item[2],
            "low": item[3],
            "close": item[4],
            "vol": item[5],
            "vol_ccy": item[6],
            "vol_ccy_quote": item[7],
            "confirm": item[8],
        })
    return klines


def format_timestamp(timestamp_ms: int) -> str:
    """格式化时间戳为可读字符串"""
    return datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def truncate_string(s: str, max_length: int = 100) -> str:
    """截断字符串"""
    if len(s) <= max_length:
        return s
    return s[:max_length] + "..."
