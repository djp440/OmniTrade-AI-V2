"""CSV存储工具，支持追加写入交易记录。"""

from __future__ import annotations

import asyncio
import csv
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.infrastructure.logger import Logger


@dataclass
class TradeRecord:
    """交易记录。"""

    timestamp: str
    inst_id: str
    position_direction: str
    position_size: str
    entry_avg_price: str
    exit_avg_price: str
    realized_pnl: str
    balance_after_close: str
    order_id: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradeRecord:
        """从字典创建交易记录。"""
        return cls(
            timestamp=str(data.get("timestamp", "")),
            inst_id=str(data.get("inst_id", "")),
            position_direction=str(data.get("position_direction", "")),
            position_size=str(data.get("position_size", "")),
            entry_avg_price=str(data.get("entry_avg_price", "")),
            exit_avg_price=str(data.get("exit_avg_price", "")),
            realized_pnl=str(data.get("realized_pnl", "")),
            balance_after_close=str(data.get("balance_after_close", "")),
            order_id=str(data.get("order_id", "")),
        )

    def to_dict(self) -> dict[str, str]:
        """转换为字典。"""
        return {
            "timestamp": self.timestamp,
            "inst_id": self.inst_id,
            "position_direction": self.position_direction,
            "position_size": self.position_size,
            "entry_avg_price": self.entry_avg_price,
            "exit_avg_price": self.exit_avg_price,
            "realized_pnl": self.realized_pnl,
            "balance_after_close": self.balance_after_close,
            "order_id": self.order_id,
        }


class CSVStorage:
    """CSV存储器，支持追加写入交易记录。"""

    HEADERS = [
        "timestamp",
        "inst_id",
        "position_direction",
        "position_size",
        "entry_avg_price",
        "exit_avg_price",
        "realized_pnl",
        "balance_after_close",
        "order_id",
    ]

    def __init__(self, filepath: str) -> None:
        """初始化CSV存储器。

        Args:
            filepath: CSV文件路径
        """
        self._logger = Logger()
        self._filepath = Path(filepath)
        self._lock = asyncio.Lock()

    async def append(self, record: TradeRecord) -> None:
        """追加写入交易记录。

        Args:
            record: 交易记录
        """
        async with self._lock:
            await asyncio.to_thread(self._append_sync, record)

    async def append_many(self, records: list[TradeRecord]) -> None:
        """批量追加交易记录。

        Args:
            records: 交易记录列表
        """
        if not records:
            return

        async with self._lock:
            await asyncio.to_thread(self._append_many_sync, records)

    async def ensure_file_exists(self) -> None:
        """确保文件存在，不存在则创建并写入表头。"""
        async with self._lock:
            await asyncio.to_thread(self._ensure_file_exists_sync)

    def _append_sync(self, record: TradeRecord) -> None:
        """同步追加写入单条记录。"""
        self._ensure_file_exists_sync()

        with open(self._filepath, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.HEADERS)
            writer.writerow(record.to_dict())

        self._logger.debug(f"交易记录已写入: {record.inst_id} {record.order_id}")

    def _append_many_sync(self, records: list[TradeRecord]) -> None:
        """同步批量追加写入记录。"""
        self._ensure_file_exists_sync()

        with open(self._filepath, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.HEADERS)
            for record in records:
                writer.writerow(record.to_dict())

        self._logger.debug(f"批量交易记录已写入: {len(records)}条")

    def _ensure_file_exists_sync(self) -> None:
        """同步确保文件存在。"""
        if self._filepath.exists():
            return

        self._filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(self._filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.HEADERS)
            writer.writeheader()

        self._logger.info(f"CSV文件已创建: {self._filepath}")

    async def read_all(self) -> list[TradeRecord]:
        """读取所有交易记录。

        Returns:
            交易记录列表
        """
        async with self._lock:
            return await asyncio.to_thread(self._read_all_sync)

    def _read_all_sync(self) -> list[TradeRecord]:
        """同步读取所有记录。"""
        if not self._filepath.exists():
            return []

        records = []
        with open(self._filepath, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(TradeRecord.from_dict(row))

        return records

    def get_file_path(self) -> Path:
        """获取文件路径。"""
        return self._filepath
