"""历史记录管理服务单元测试"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest import IsolatedAsyncioTestCase

from src.domain.events import PositionCloseEvent
from src.domain.trading import Position, PositionDirection, TradeRecord
from src.services.history_service import HistoryService


class TestHistoryService(IsolatedAsyncioTestCase):
    """历史记录服务测试类"""

    def setUp(self) -> None:
        """设置测试数据"""
        self.max_history_length = 5
        self.service = HistoryService(max_history_length=self.max_history_length)

    def test_init(self) -> None:
        """测试历史记录服务初始化"""
        self.assertEqual(self.service._max_history_length, self.max_history_length)
        self.assertEqual(len(self.service._histories), 0)

    def test_add_analysis_record_new_inst_id(self) -> None:
        """测试为新交易对添加分析记录"""
        inst_id = "BTC-USDT-SWAP"
        analysis = "看涨，EMA20支撑有效，建议开多仓，止损41000，止盈45000"

        self.service.add_analysis_record(inst_id, analysis)

        self.assertEqual(self.service.get_history_count(inst_id), 1)
        self.assertEqual(self.service.get_history(inst_id), [analysis])

    def test_add_analysis_record_multiple(self) -> None:
        """测试添加多条分析记录"""
        inst_id = "BTC-USDT-SWAP"

        for i in range(3):
            self.service.add_analysis_record(inst_id, f"分析记录{i + 1}")

        self.assertEqual(self.service.get_history_count(inst_id), 3)
        history = self.service.get_history(inst_id)
        self.assertEqual(history, ["分析记录1", "分析记录2", "分析记录3"])

    def test_add_analysis_record_exceeds_limit(self) -> None:
        """测试超出长度限制时自动删除最早记录"""
        inst_id = "BTC-USDT-SWAP"

        for i in range(self.max_history_length + 2):
            self.service.add_analysis_record(inst_id, f"分析记录{i + 1}")

        self.assertEqual(self.service.get_history_count(inst_id), self.max_history_length)
        history = self.service.get_history(inst_id)
        self.assertEqual(history[0], "分析记录3")
        self.assertEqual(history[-1], "分析记录7")

    def test_add_analysis_record_multiple_inst_ids(self) -> None:
        """测试多个交易对独立维护历史记录"""
        btc_analysis = "BTC看涨"
        eth_analysis = "ETH看跌"

        self.service.add_analysis_record("BTC-USDT-SWAP", btc_analysis)
        self.service.add_analysis_record("ETH-USDT-SWAP", eth_analysis)

        self.assertEqual(self.service.get_history("BTC-USDT-SWAP"), [btc_analysis])
        self.assertEqual(self.service.get_history("ETH-USDT-SWAP"), [eth_analysis])

    def test_get_history_empty(self) -> None:
        """测试获取空历史记录"""
        history = self.service.get_history("BTC-USDT-SWAP")
        self.assertEqual(history, [])

    def test_get_history_text(self) -> None:
        """测试获取格式化的历史记录文本"""
        inst_id = "BTC-USDT-SWAP"

        self.service.add_analysis_record(inst_id, "分析1")
        self.service.add_analysis_record(inst_id, "分析2")

        text = self.service.get_history_text(inst_id)
        expected = "1. 分析1\n2. 分析2"
        self.assertEqual(text, expected)

    def test_get_history_text_empty(self) -> None:
        """测试获取空历史记录文本"""
        text = self.service.get_history_text("BTC-USDT-SWAP")
        self.assertEqual(text, "无")

    def test_clear_history(self) -> None:
        """测试清空指定交易对的历史记录"""
        inst_id = "BTC-USDT-SWAP"

        self.service.add_analysis_record(inst_id, "分析1")
        self.service.add_analysis_record(inst_id, "分析2")
        self.assertEqual(self.service.get_history_count(inst_id), 2)

        self.service.clear_history(inst_id)

        self.assertEqual(self.service.get_history_count(inst_id), 0)
        self.assertEqual(self.service.get_history(inst_id), [])

    def test_clear_history_nonexistent(self) -> None:
        """测试清空不存在的交易对历史记录"""
        self.service.clear_history("NONEXISTENT-USDT-SWAP")

    def test_clear_all_history(self) -> None:
        """测试清空所有交易对的历史记录"""
        self.service.add_analysis_record("BTC-USDT-SWAP", "BTC分析")
        self.service.add_analysis_record("ETH-USDT-SWAP", "ETH分析")

        self.service.clear_all_history()

        self.assertEqual(self.service.get_history_count("BTC-USDT-SWAP"), 0)
        self.assertEqual(self.service.get_history_count("ETH-USDT-SWAP"), 0)

    async def test_on_position_close(self) -> None:
        """测试处理平仓完成事件"""
        inst_id = "BTC-USDT-SWAP"

        self.service.add_analysis_record(inst_id, "分析1")
        self.service.add_analysis_record(inst_id, "分析2")
        self.assertEqual(self.service.get_history_count(inst_id), 2)

        position = Position(
            inst_id=inst_id,
            direction=PositionDirection.LONG,
            size=Decimal("1.0"),
            entry_price=Decimal("42000"),
        )
        trade_record = TradeRecord(
            timestamp=1705312800000,
            inst_id=inst_id,
            position_direction=PositionDirection.LONG,
            position_size=Decimal("1.0"),
            entry_avg_price=Decimal("42000"),
            exit_avg_price=Decimal("43000"),
            realized_pnl=Decimal("1000"),
            balance_after_close=Decimal("10000"),
            order_id="test-order-id",
        )
        event = PositionCloseEvent(
            inst_id=inst_id,
            closed_position=position,
            balance_after_close=Decimal("10000"),
            trade_record=trade_record,
        )

        await self.service.on_position_close(event)

        self.assertEqual(self.service.get_history_count(inst_id), 0)

    def test_get_history_count(self) -> None:
        """测试获取历史记录数量"""
        inst_id = "BTC-USDT-SWAP"

        self.assertEqual(self.service.get_history_count(inst_id), 0)

        self.service.add_analysis_record(inst_id, "分析1")
        self.assertEqual(self.service.get_history_count(inst_id), 1)

        self.service.add_analysis_record(inst_id, "分析2")
        self.assertEqual(self.service.get_history_count(inst_id), 2)

    def test_is_history_full(self) -> None:
        """测试检查历史记录是否已满"""
        inst_id = "BTC-USDT-SWAP"

        self.assertFalse(self.service.is_history_full(inst_id))

        for i in range(self.max_history_length):
            self.assertFalse(self.service.is_history_full(inst_id))
            self.service.add_analysis_record(inst_id, f"分析{i + 1}")

        self.assertTrue(self.service.is_history_full(inst_id))

    def test_is_history_full_nonexistent(self) -> None:
        """测试检查不存在的交易对历史记录是否已满"""
        self.assertFalse(self.service.is_history_full("NONEXISTENT-USDT-SWAP"))

    def test_history_fifo_order(self) -> None:
        """测试历史记录按FIFO顺序维护"""
        inst_id = "BTC-USDT-SWAP"
        max_len = 3
        service = HistoryService(max_history_length=max_len)

        for i in range(5):
            service.add_analysis_record(inst_id, f"记录{i + 1}")

        history = service.get_history(inst_id)
        self.assertEqual(len(history), max_len)
        self.assertEqual(history, ["记录3", "记录4", "记录5"])
