"""历史记录管理服务集成测试"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest import IsolatedAsyncioTestCase

from src.domain.events import PositionCloseEvent
from src.domain.trading import Position, PositionDirection, TradeRecord
from src.services.history_service import HistoryService


class TestHistoryServiceIntegration(IsolatedAsyncioTestCase):
    """历史记录服务集成测试类"""

    def setUp(self) -> None:
        """设置测试数据"""
        self.service = HistoryService(max_history_length=10)

    def test_full_workflow_single_pair(self) -> None:
        """测试单个交易对的完整工作流"""
        inst_id = "BTC-USDT-SWAP"

        for i in range(5):
            self.service.add_analysis_record(inst_id, f"第{i + 1}次分析：看涨，建议开多")

        self.assertEqual(self.service.get_history_count(inst_id), 5)

        history_text = self.service.get_history_text(inst_id)
        self.assertIn("1. 第1次分析", history_text)
        self.assertIn("5. 第5次分析", history_text)

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

        asyncio.run(self.service.on_position_close(event))

        self.assertEqual(self.service.get_history_count(inst_id), 0)

    def test_full_workflow_multiple_pairs(self) -> None:
        """测试多个交易对的完整工作流"""
        btc_id = "BTC-USDT-SWAP"
        eth_id = "ETH-USDT-SWAP"

        for i in range(3):
            self.service.add_analysis_record(btc_id, f"BTC分析{i + 1}")
            self.service.add_analysis_record(eth_id, f"ETH分析{i + 1}")

        self.assertEqual(self.service.get_history_count(btc_id), 3)
        self.assertEqual(self.service.get_history_count(eth_id), 3)

        btc_position = Position(
            inst_id=btc_id,
            direction=PositionDirection.LONG,
            size=Decimal("1.0"),
            entry_price=Decimal("42000"),
        )
        btc_trade_record = TradeRecord(
            timestamp=1705312800000,
            inst_id=btc_id,
            position_direction=PositionDirection.LONG,
            position_size=Decimal("1.0"),
            entry_avg_price=Decimal("42000"),
            exit_avg_price=Decimal("43000"),
            realized_pnl=Decimal("1000"),
            balance_after_close=Decimal("10000"),
            order_id="btc-order-id",
        )
        btc_event = PositionCloseEvent(
            inst_id=btc_id,
            closed_position=btc_position,
            balance_after_close=Decimal("10000"),
            trade_record=btc_trade_record,
        )

        asyncio.run(self.service.on_position_close(btc_event))

        self.assertEqual(self.service.get_history_count(btc_id), 0)
        self.assertEqual(self.service.get_history_count(eth_id), 3)

    def test_history_rotation_with_trading(self) -> None:
        """测试历史记录轮换与交易的集成"""
        inst_id = "BTC-USDT-SWAP"
        max_len = 5
        service = HistoryService(max_history_length=max_len)

        for i in range(3):
            service.add_analysis_record(inst_id, f"分析{i + 1}")

        self.assertEqual(service.get_history_count(inst_id), 3)

        for i in range(10):
            service.add_analysis_record(inst_id, f"新分析{i + 1}")

        self.assertEqual(service.get_history_count(inst_id), max_len)

        position = Position(
            inst_id=inst_id,
            direction=PositionDirection.SHORT,
            size=Decimal("1.0"),
            entry_price=Decimal("43000"),
        )
        trade_record = TradeRecord(
            timestamp=1705312800000,
            inst_id=inst_id,
            position_direction=PositionDirection.SHORT,
            position_size=Decimal("1.0"),
            entry_avg_price=Decimal("43000"),
            exit_avg_price=Decimal("42000"),
            realized_pnl=Decimal("1000"),
            balance_after_close=Decimal("11000"),
            order_id="short-order-id",
        )
        event = PositionCloseEvent(
            inst_id=inst_id,
            closed_position=position,
            balance_after_close=Decimal("11000"),
            trade_record=trade_record,
        )

        asyncio.run(service.on_position_close(event))

        self.assertEqual(service.get_history_count(inst_id), 0)

    def test_event_handler_registration(self) -> None:
        """测试事件处理器注册"""
        inst_id = "BTC-USDT-SWAP"

        self.service.add_analysis_record(inst_id, "分析1")
        self.assertEqual(self.service.get_history_count(inst_id), 1)

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

        asyncio.run(self.service.on_position_close(event))

        self.assertEqual(self.service.get_history_count(inst_id), 0)

    def test_complex_trading_scenario(self) -> None:
        """测试复杂交易场景"""
        btc_id = "BTC-USDT-SWAP"
        eth_id = "ETH-USDT-SWAP"

        self.service.add_analysis_record(btc_id, "BTC第1次分析：看涨")
        self.service.add_analysis_record(eth_id, "ETH第1次分析：看跌")

        self.service.add_analysis_record(btc_id, "BTC第2次分析：继续看涨")
        self.service.add_analysis_record(eth_id, "ETH第2次分析：继续看跌")

        btc_history = self.service.get_history(btc_id)
        eth_history = self.service.get_history(eth_id)

        self.assertEqual(len(btc_history), 2)
        self.assertEqual(len(eth_history), 2)

        btc_position = Position(
            inst_id=btc_id,
            direction=PositionDirection.LONG,
            size=Decimal("1.0"),
            entry_price=Decimal("42000"),
        )
        btc_trade_record = TradeRecord(
            timestamp=1705312800000,
            inst_id=btc_id,
            position_direction=PositionDirection.LONG,
            position_size=Decimal("1.0"),
            entry_avg_price=Decimal("42000"),
            exit_avg_price=Decimal("43000"),
            realized_pnl=Decimal("1000"),
            balance_after_close=Decimal("10000"),
            order_id="btc-close-id",
        )
        btc_event = PositionCloseEvent(
            inst_id=btc_id,
            closed_position=btc_position,
            balance_after_close=Decimal("10000"),
            trade_record=btc_trade_record,
        )

        asyncio.run(self.service.on_position_close(btc_event))

        self.assertEqual(self.service.get_history_count(btc_id), 0)
        self.assertEqual(self.service.get_history_count(eth_id), 2)

        self.service.add_analysis_record(btc_id, "BTC新周期第1次分析")
        self.assertEqual(self.service.get_history_count(btc_id), 1)
