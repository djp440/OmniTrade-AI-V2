"""交易服务单元测试"""

from __future__ import annotations

import asyncio
import os
import tempfile
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.config import TradePairConfig
from src.domain.events import TradeCompleteEvent, TradeExecutionResult
from src.domain.trading import (
    Position,
    PositionDirection,
    TradeInstruction,
    TradeOperation,
    TradeRecord,
)
from src.infrastructure.csv_storage import CSVStorage
from src.services.trading_service import TradingService, TradingServiceError


@pytest.fixture
def temp_csv_file():
    """创建临时CSV文件"""
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def mock_okx_client():
    """创建模拟OKX客户端"""
    client = MagicMock()
    client.set_position_mode = AsyncMock(return_value={"code": "0", "data": []})
    client.set_leverage = AsyncMock(return_value={"code": "0", "data": []})
    client.get_positions = AsyncMock(return_value={"code": "0", "data": []})
    client.get_balance = AsyncMock(
        return_value={
            "code": "0",
            "data": [{"details": [{"ccy": "USDT", "availBal": "10000"}]}],
        }
    )
    client.place_order = AsyncMock(
        return_value={"code": "0", "data": [{"ordId": "test-order-id"}]}
    )
    client.close_position = AsyncMock(
        return_value={"code": "0", "data": [{"ordId": "close-order-id"}]}
    )
    client.get_instrument = AsyncMock(
        return_value={"code": "0", "data": [{"ctVal": "0.01", "ctValCcy": "BTC"}]}
    )
    client.get_candles = AsyncMock(
        return_value={"code": "0", "data": [["1234567890000", "50000", "51000", "49000", "50000", "100", "1"]]}
    )
    return client


@pytest.fixture
def trade_pair_config():
    """创建交易对配置"""
    return TradePairConfig(
        inst_id="BTC-USDT-SWAP",
        timeframe="1H",
        leverage=10,
        position_size=Decimal("100"),
        stop_loss_ratio=Decimal("0.02"),
        take_profit_ratio=Decimal("0.05"),
    )


@pytest.fixture
def trading_service(mock_okx_client, temp_csv_file, trade_pair_config):
    """创建交易服务实例"""
    csv_storage = CSVStorage(temp_csv_file)
    service = TradingService(
        okx_client=mock_okx_client,
        csv_storage=csv_storage,
        trade_pairs_config=[trade_pair_config],
        td_mode="isolated",
    )
    return service


class TestTradingServiceInitialization:
    """测试交易服务初始化"""

    @pytest.mark.asyncio
    async def test_initialize_success(self, trading_service, mock_okx_client):
        """测试初始化成功"""
        await trading_service.initialize()

        mock_okx_client.set_position_mode.assert_called_once_with("net_mode")
        mock_okx_client.set_leverage.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_already_set_position_mode(self, trading_service, mock_okx_client):
        """测试持仓模式已设置的情况"""
        mock_okx_client.set_position_mode.side_effect = Exception("51000: already set")

        # 不应该抛出异常
        await trading_service.initialize()

    @pytest.mark.asyncio
    async def test_initialize_set_leverage_failure(self, trading_service, mock_okx_client):
        """测试设置杠杆失败"""
        mock_okx_client.set_leverage.side_effect = Exception("API Error")

        with pytest.raises(TradingServiceError):
            await trading_service.initialize()


class TestGetPosition:
    """测试获取仓位"""

    @pytest.mark.asyncio
    async def test_get_position_empty(self, trading_service, mock_okx_client):
        """测试获取空仓"""
        mock_okx_client.get_positions.return_value = {"code": "0", "data": []}

        position = await trading_service.get_position("BTC-USDT-SWAP")

        assert position.is_empty()
        assert position.direction == PositionDirection.EMPTY

    @pytest.mark.asyncio
    async def test_get_position_long(self, trading_service, mock_okx_client):
        """测试获取多仓"""
        mock_okx_client.get_positions.return_value = {
            "code": "0",
            "data": [
                {
                    "pos": "1.5",
                    "avgPx": "50000",
                    "upl": "100",
                }
            ],
        }

        position = await trading_service.get_position("BTC-USDT-SWAP")

        assert not position.is_empty()
        assert position.direction == PositionDirection.LONG
        assert position.size == Decimal("1.5")
        assert position.entry_price == Decimal("50000")

    @pytest.mark.asyncio
    async def test_get_position_short(self, trading_service, mock_okx_client):
        """测试获取空仓"""
        mock_okx_client.get_positions.return_value = {
            "code": "0",
            "data": [
                {
                    "pos": "-1.5",
                    "avgPx": "50000",
                    "upl": "-50",
                }
            ],
        }

        position = await trading_service.get_position("BTC-USDT-SWAP")

        assert not position.is_empty()
        assert position.direction == PositionDirection.SHORT
        assert position.size == Decimal("1.5")


class TestGetBalance:
    """测试获取余额"""

    @pytest.mark.asyncio
    async def test_get_balance_success(self, trading_service, mock_okx_client):
        """测试获取余额成功"""
        balance = await trading_service.get_balance("USDT")

        assert balance == Decimal("10000")

    @pytest.mark.asyncio
    async def test_get_balance_empty(self, trading_service, mock_okx_client):
        """测试获取空余额"""
        mock_okx_client.get_balance.return_value = {"code": "0", "data": []}

        balance = await trading_service.get_balance("USDT")

        assert balance == Decimal("0")


class TestValidateInstruction:
    """测试指令验证"""

    def test_validate_entry_params_success(self, trading_service, trade_pair_config):
        """测试开仓参数验证成功"""
        instruction = TradeInstruction(
            op=TradeOperation.ENTRY_LONG,
            args={
                "size": "100",
                "stop_loss": "49000",
                "take_profit": "52500",
            },
        )

        # 不应该抛出异常
        trading_service._validate_instruction_params(instruction, trade_pair_config)

    def test_validate_entry_params_exceed_size_limit(self, trading_service, trade_pair_config):
        """测试开仓金额超过限制"""
        instruction = TradeInstruction(
            op=TradeOperation.ENTRY_LONG,
            args={
                "size": "200",
                "stop_loss": "49000",
                "take_profit": "52500",
            },
        )

        with pytest.raises(ValueError, match="超过配置限制"):
            trading_service._validate_instruction_params(instruction, trade_pair_config)

    def test_validate_entry_against_empty_position(self, trading_service):
        """测试开仓时仓位为空"""
        instruction = TradeInstruction(
            op=TradeOperation.ENTRY_LONG,
            args={"size": "100", "stop_loss": "49000", "take_profit": "52500"},
        )
        position = Position(inst_id="BTC-USDT-SWAP")

        # 空仓可以开仓
        trading_service._validate_instruction_against_position(instruction, position)

    def test_validate_entry_against_opposite_position(self, trading_service):
        """测试开仓时已有反向仓位"""
        instruction = TradeInstruction(
            op=TradeOperation.ENTRY_LONG,
            args={"size": "100", "stop_loss": "49000", "take_profit": "52500"},
        )
        position = Position(
            inst_id="BTC-USDT-SWAP",
            direction=PositionDirection.SHORT,
            size=Decimal("1"),
        )

        with pytest.raises(ValueError, match="已有short仓位"):
            trading_service._validate_instruction_against_position(instruction, position)

    def test_validate_exit_against_empty_position(self, trading_service):
        """测试减仓时仓位为空"""
        instruction = TradeInstruction(
            op=TradeOperation.EXIT_LONG,
            args={"size": "0.5"},
        )
        position = Position(inst_id="BTC-USDT-SWAP")

        with pytest.raises(ValueError, match="空仓无法执行"):
            trading_service._validate_instruction_against_position(instruction, position)

    def test_validate_exit_exceed_size(self, trading_service):
        """测试减仓数量超过持仓"""
        instruction = TradeInstruction(
            op=TradeOperation.EXIT_LONG,
            args={"size": "2"},
        )
        position = Position(
            inst_id="BTC-USDT-SWAP",
            direction=PositionDirection.LONG,
            size=Decimal("1"),
        )

        with pytest.raises(ValueError, match="必须小于当前持仓"):
            trading_service._validate_instruction_against_position(instruction, position)

    def test_validate_close_empty_position(self, trading_service):
        """测试平仓时仓位为空"""
        instruction = TradeInstruction(op=TradeOperation.CLOSE_POSITION)
        position = Position(inst_id="BTC-USDT-SWAP")

        with pytest.raises(ValueError, match="空仓无法执行平仓"):
            trading_service._validate_instruction_against_position(instruction, position)


class TestExecuteInstruction:
    """测试指令执行"""

    @pytest.mark.asyncio
    async def test_execute_entry_long(self, trading_service, mock_okx_client):
        """测试执行开多仓"""
        instruction = TradeInstruction(
            op=TradeOperation.ENTRY_LONG,
            args={"size": "100", "stop_loss": "49000", "take_profit": "52500"},
        )

        result = await trading_service.execute_instruction("BTC-USDT-SWAP", instruction)

        assert isinstance(result, TradeCompleteEvent)
        assert result.execution_result.success
        assert result.order_id == "test-order-id"
        mock_okx_client.place_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_entry_short(self, trading_service, mock_okx_client):
        """测试执行开空仓"""
        instruction = TradeInstruction(
            op=TradeOperation.ENTRY_SHORT,
            args={"size": "100", "stop_loss": "51000", "take_profit": "47500"},
        )

        result = await trading_service.execute_instruction("BTC-USDT-SWAP", instruction)

        assert result.execution_result.success
        mock_okx_client.place_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_close_position(self, trading_service, mock_okx_client):
        """测试执行平仓"""
        # 先设置有仓位
        mock_okx_client.get_positions.return_value = {
            "code": "0",
            "data": [{"pos": "1.5", "avgPx": "50000", "upl": "100"}],
        }

        instruction = TradeInstruction(op=TradeOperation.CLOSE_POSITION)

        result = await trading_service.execute_instruction("BTC-USDT-SWAP", instruction)

        assert result.execution_result.success
        mock_okx_client.close_position.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_exit_long(self, trading_service, mock_okx_client):
        """测试执行多仓减仓"""
        mock_okx_client.get_positions.return_value = {
            "code": "0",
            "data": [{"pos": "1.5", "avgPx": "50000", "upl": "100"}],
        }

        instruction = TradeInstruction(
            op=TradeOperation.EXIT_LONG,
            args={"size": "0.5"},
        )

        result = await trading_service.execute_instruction("BTC-USDT-SWAP", instruction)

        assert result.execution_result.success
        mock_okx_client.place_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_validation_failure(self, trading_service):
        """测试验证失败"""
        # 使用完整的参数，但超过金额限制
        instruction = TradeInstruction(
            op=TradeOperation.ENTRY_LONG,
            args={"size": "200", "stop_loss": "49000", "take_profit": "52500"},  # 超过100的限制
        )

        result = await trading_service.execute_instruction("BTC-USDT-SWAP", instruction)

        assert not result.execution_result.success
        assert result.execution_result.error_message is not None
        assert "超过配置限制" in result.execution_result.error_message


class TestExecuteInstructions:
    """测试批量执行指令"""

    @pytest.mark.asyncio
    async def test_execute_multiple_instructions(self, trading_service, mock_okx_client):
        """测试批量执行多个指令"""
        instructions = [
            TradeInstruction(
                op=TradeOperation.ENTRY_LONG,
                args={"size": "100", "stop_loss": "49000", "take_profit": "52500"},
            ),
            TradeInstruction(
                op=TradeOperation.CLOSE_POSITION,
            ),
        ]

        # 第一个指令需要空仓，第二个需要持仓
        mock_okx_client.get_positions.side_effect = [
            {"code": "0", "data": []},  # 第一个指令：空仓
            {"code": "0", "data": [{"pos": "1", "avgPx": "50000", "upl": "0"}]},  # 第二个指令：有持仓
        ]

        results = await trading_service.execute_instructions("BTC-USDT-SWAP", instructions)

        assert len(results) == 2
        assert all(isinstance(r, TradeCompleteEvent) for r in results)


class TestHandlePositionClose:
    """测试平仓后处理"""

    @pytest.mark.asyncio
    async def test_handle_position_close(self, trading_service, temp_csv_file):
        """测试平仓后处理"""
        closed_position = Position(
            inst_id="BTC-USDT-SWAP",
            direction=PositionDirection.LONG,
            size=Decimal("1.5"),
            entry_price=Decimal("50000"),
            unrealized_pnl=Decimal("100"),
        )

        event = await trading_service.handle_position_close(
            inst_id="BTC-USDT-SWAP",
            closed_position=closed_position,
            balance_after_close=Decimal("10100"),
            order_id="close-order-123",
        )

        assert event.inst_id == "BTC-USDT-SWAP"
        assert event.balance_after_close == Decimal("10100")
        assert isinstance(event.trade_record, TradeRecord)

        # 验证CSV文件已写入
        with open(temp_csv_file, "r") as f:
            content = f.read()
            assert "BTC-USDT-SWAP" in content
            assert "close-order-123" in content


class TestClientOidGeneration:
    """测试客户端订单ID生成"""

    def test_generate_client_oid_format(self, trading_service):
        """测试生成的client_oid格式

        OKX要求clOrdId长度不超过32个字符。
        """
        oid1 = trading_service.generate_client_oid()
        oid2 = trading_service.generate_client_oid()

        # OKX要求最多32字符
        assert len(oid1) == 32
        assert len(oid2) == 32
        assert len(oid1) <= 32
        assert len(oid2) <= 32
        assert oid1 != oid2  # 应该唯一

        # 验证是十六进制格式（无连字符的UUID）
        assert oid1.isalnum()
        assert oid2.isalnum()
