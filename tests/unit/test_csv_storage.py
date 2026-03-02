"""CSV存储工具单元测试。"""

import asyncio
import csv
import os
import tempfile
import unittest

from src.infrastructure.csv_storage import CSVStorage, TradeRecord


class TestCSVStorage(unittest.IsolatedAsyncioTestCase):
    """CSV存储器测试类。"""

    async def asyncSetUp(self):
        """异步测试前置。"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.filepath = os.path.join(self.temp_dir.name, "test_trades.csv")
        self.storage = CSVStorage(self.filepath)

    async def asyncTearDown(self):
        """异步测试后置。"""
        self.temp_dir.cleanup()

    def _create_sample_record(self, suffix: str = "") -> TradeRecord:
        """创建示例交易记录。"""
        return TradeRecord(
            timestamp=f"2024-01-01 12:00:00{suffix}",
            inst_id=f"BTC-USDT-SWAP{suffix}",
            position_direction="long",
            position_size="1.5",
            entry_avg_price="50000.00",
            exit_avg_price="51000.00",
            realized_pnl="1500.00",
            balance_after_close="10000.00",
            order_id=f"test-order-id{suffix}",
        )

    async def test_ensure_file_exists_creates_file_with_headers(self):
        """测试确保文件存在时创建文件和表头。"""
        await self.storage.ensure_file_exists()

        self.assertTrue(os.path.exists(self.filepath))

        with open(self.filepath, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)

        expected_headers = [
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
        self.assertEqual(headers, expected_headers)

    async def test_append_creates_file_if_not_exists(self):
        """测试追加时自动创建文件。"""
        record = self._create_sample_record()

        await self.storage.append(record)

        self.assertTrue(os.path.exists(self.filepath))

        with open(self.filepath, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["inst_id"], "BTC-USDT-SWAP")

    async def test_append_multiple_records(self):
        """测试追加多条记录。"""
        records = [
            self._create_sample_record("1"),
            self._create_sample_record("2"),
            self._create_sample_record("3"),
        ]

        for record in records:
            await self.storage.append(record)

        with open(self.filepath, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        self.assertEqual(len(rows), 3)

    async def test_append_many_records(self):
        """测试批量追加记录。"""
        records = [
            self._create_sample_record("1"),
            self._create_sample_record("2"),
        ]

        await self.storage.append_many(records)

        with open(self.filepath, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        self.assertEqual(len(rows), 2)

    async def test_append_many_empty_list(self):
        """测试批量追加空列表。"""
        await self.storage.append_many([])

        self.assertFalse(os.path.exists(self.filepath))

    async def test_read_all_records(self):
        """测试读取所有记录。"""
        records = [
            self._create_sample_record("1"),
            self._create_sample_record("2"),
        ]

        for record in records:
            await self.storage.append(record)

        read_records = await self.storage.read_all()

        self.assertEqual(len(read_records), 2)
        self.assertEqual(read_records[0].inst_id, "BTC-USDT-SWAP1")
        self.assertEqual(read_records[1].inst_id, "BTC-USDT-SWAP2")

    async def test_read_all_empty_file(self):
        """测试读取空文件。"""
        await self.storage.ensure_file_exists()

        records = await self.storage.read_all()

        self.assertEqual(len(records), 0)

    async def test_read_all_nonexistent_file(self):
        """测试读取不存在的文件。"""
        records = await self.storage.read_all()

        self.assertEqual(len(records), 0)

    async def test_trade_record_from_dict(self):
        """测试从字典创建交易记录。"""
        data = {
            "timestamp": "2024-01-01 12:00:00",
            "inst_id": "ETH-USDT-SWAP",
            "position_direction": "short",
            "position_size": "2.0",
            "entry_avg_price": "3000.00",
            "exit_avg_price": "2900.00",
            "realized_pnl": "-200.00",
            "balance_after_close": "8000.00",
            "order_id": "order-123",
        }

        record = TradeRecord.from_dict(data)

        self.assertEqual(record.timestamp, "2024-01-01 12:00:00")
        self.assertEqual(record.inst_id, "ETH-USDT-SWAP")
        self.assertEqual(record.position_direction, "short")
        self.assertEqual(record.order_id, "order-123")

    async def test_trade_record_to_dict(self):
        """测试交易记录转换为字典。"""
        record = self._create_sample_record()

        data = record.to_dict()

        self.assertEqual(data["timestamp"], "2024-01-01 12:00:00")
        self.assertEqual(data["inst_id"], "BTC-USDT-SWAP")
        self.assertEqual(data["order_id"], "test-order-id")

    async def test_concurrent_append(self):
        """测试并发追加。"""
        records = [self._create_sample_record(str(i)) for i in range(10)]

        tasks = [self.storage.append(record) for record in records]
        await asyncio.gather(*tasks)

        read_records = await self.storage.read_all()

        self.assertEqual(len(read_records), 10)


if __name__ == "__main__":
    unittest.main()
