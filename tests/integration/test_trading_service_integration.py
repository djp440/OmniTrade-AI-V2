"""交易服务集成测试

在OKX模拟盘环境测试交易服务。
"""

from __future__ import annotations

import os
import tempfile
from decimal import Decimal

import pytest

from src.domain.config import TradePairConfig
from src.domain.trading import (
    PositionDirection,
    TradeInstruction,
    TradeOperation,
)
from src.infrastructure.config_loader import load_config
from src.infrastructure.csv_storage import CSVStorage
from src.infrastructure.okx_auth import OkxCredentials
from src.infrastructure.okx_rest_client import OkxRestClient
from src.services.trading_service import TradingService


@pytest.fixture(scope="module")
def okx_client():
    """创建OKX客户端（模拟盘）"""
    # 从环境变量加载配置
    api_key = os.getenv("OKX_DEMO_API_KEY", "")
    api_secret = os.getenv("OKX_DEMO_API_SECRET", "")
    passphrase = os.getenv("OKX_DEMO_PASSPHRASE", "")

    if not all([api_key, api_secret, passphrase]):
        pytest.skip("未配置OKX模拟盘API密钥")

    credentials = OkxCredentials(
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
    )

    client = OkxRestClient(credentials, is_simulated=True)
    return client


@pytest.fixture
def temp_csv_file():
    """创建临时CSV文件"""
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
async def trading_service(okx_client, temp_csv_file):
    """创建交易服务实例"""
    csv_storage = CSVStorage(temp_csv_file)
    trade_pair_config = TradePairConfig(
        inst_id="BTC-USDT-SWAP",
        timeframe="1H",
        leverage=10,
        position_size=Decimal("10"),  # 小额测试
        stop_loss_ratio=Decimal("0.02"),
        take_profit_ratio=Decimal("0.05"),
    )

    service = TradingService(
        okx_client=okx_client,
        csv_storage=csv_storage,
        trade_pairs_config=[trade_pair_config],
        td_mode="cross",
    )

    # 初始化
    await service.initialize()

    yield service

    # 清理：确保没有遗留仓位
    try:
        position = await service.get_position("BTC-USDT-SWAP")
        if not position.is_empty():
            await okx_client.close_position(
                inst_id="BTC-USDT-SWAP",
                mgn_mode="cross",
                auto_cxl=True,
            )
    except Exception:
        pass


@pytest.mark.asyncio
@pytest.mark.integration
class TestTradingServiceIntegration:
    """交易服务集成测试类"""

    async def test_initialize_and_get_balance(self, trading_service):
        """测试初始化和获取余额"""
        balance = await trading_service.get_balance("USDT")
        assert balance >= 0

    async def test_get_position_empty(self, trading_service):
        """测试获取空仓"""
        # 确保没有仓位
        position = await trading_service.get_position("BTC-USDT-SWAP")
        
        # 如果有仓位先平仓
        if not position.is_empty():
            await trading_service._okx_client.close_position(
                inst_id="BTC-USDT-SWAP",
                mgn_mode="cross",
                auto_cxl=True,
            )
            await asyncio.sleep(1)  # 等待订单处理

        position = await trading_service.get_position("BTC-USDT-SWAP")
        assert position.is_empty()

    async def test_entry_long_and_close(self, trading_service):
        """测试开多仓和平仓"""
        # 开多仓
        instruction = TradeInstruction(
            op=TradeOperation.ENTRY_LONG,
            args={
                "size": "10",
                "stop_loss": "40000",
                "take_profit": "60000",
            },
        )

        result = await trading_service.execute_instruction("BTC-USDT-SWAP", instruction)
        assert result.execution_result.success, f"开仓失败: {result.execution_result.error_message}"
        assert result.order_id is not None

        # 等待订单处理
        import asyncio
        await asyncio.sleep(2)

        # 验证仓位
        position = await trading_service.get_position("BTC-USDT-SWAP")
        assert not position.is_empty()
        assert position.direction == PositionDirection.LONG

        # 平仓
        close_instruction = TradeInstruction(op=TradeOperation.CLOSE_POSITION)
        close_result = await trading_service.execute_instruction("BTC-USDT-SWAP", close_instruction)
        assert close_result.execution_result.success

        # 等待订单处理
        await asyncio.sleep(2)

        # 验证仓位已清空
        position = await trading_service.get_position("BTC-USDT-SWAP")
        assert position.is_empty()

    async def test_entry_short_and_close(self, trading_service):
        """测试开空仓和平仓"""
        # 开空仓
        instruction = TradeInstruction(
            op=TradeOperation.ENTRY_SHORT,
            args={
                "size": "10",
                "stop_loss": "60000",
                "take_profit": "40000",
            },
        )

        result = await trading_service.execute_instruction("BTC-USDT-SWAP", instruction)
        assert result.execution_result.success

        # 等待订单处理
        import asyncio
        await asyncio.sleep(2)

        # 验证仓位
        position = await trading_service.get_position("BTC-USDT-SWAP")
        assert not position.is_empty()
        assert position.direction == PositionDirection.SHORT

        # 平仓
        close_instruction = TradeInstruction(op=TradeOperation.CLOSE_POSITION)
        close_result = await trading_service.execute_instruction("BTC-USDT-SWAP", close_instruction)
        assert close_result.execution_result.success

        # 等待订单处理
        await asyncio.sleep(2)

        # 验证仓位已清空
        position = await trading_service.get_position("BTC-USDT-SWAP")
        assert position.is_empty()

    async def test_exit_partial_position(self, trading_service):
        """测试部分减仓"""
        # 先开多仓
        entry_instruction = TradeInstruction(
            op=TradeOperation.ENTRY_LONG,
            args={
                "size": "10",
                "stop_loss": "40000",
                "take_profit": "60000",
            },
        )

        entry_result = await trading_service.execute_instruction("BTC-USDT-SWAP", entry_instruction)
        assert entry_result.execution_result.success

        # 等待订单处理
        import asyncio
        await asyncio.sleep(2)

        # 获取仓位
        position = await trading_service.get_position("BTC-USDT-SWAP")
        original_size = position.size
        assert original_size > 0

        # 部分减仓
        exit_instruction = TradeInstruction(
            op=TradeOperation.EXIT_LONG,
            args={"size": str(original_size / 2)},  # 减仓一半
        )

        exit_result = await trading_service.execute_instruction("BTC-USDT-SWAP", exit_instruction)
        assert exit_result.execution_result.success

        # 等待订单处理
        await asyncio.sleep(2)

        # 验证仓位减少
        position = await trading_service.get_position("BTC-USDT-SWAP")
        assert position.size < original_size

        # 清理：全平
        await trading_service._okx_client.close_position(
            inst_id="BTC-USDT-SWAP",
            mgn_mode="cross",
            auto_cxl=True,
        )
        await asyncio.sleep(2)

    async def test_validation_blocks_invalid_instruction(self, trading_service):
        """测试验证阻止非法指令"""
        # 尝试空仓时平仓
        position = await trading_service.get_position("BTC-USDT-SWAP")
        if not position.is_empty():
            await trading_service._okx_client.close_position(
                inst_id="BTC-USDT-SWAP",
                mgn_mode="cross",
                auto_cxl=True,
            )
            import asyncio
            await asyncio.sleep(2)

        close_instruction = TradeInstruction(op=TradeOperation.CLOSE_POSITION)
        result = await trading_service.execute_instruction("BTC-USDT-SWAP", close_instruction)
        
        assert not result.execution_result.success
        assert "空仓无法执行平仓" in result.execution_result.error_message

    async def test_handle_position_close_writes_csv(self, trading_service, temp_csv_file):
        """测试平仓后写入CSV"""
        # 先开仓再平仓
        entry_instruction = TradeInstruction(
            op=TradeOperation.ENTRY_LONG,
            args={
                "size": "10",
                "stop_loss": "40000",
                "take_profit": "60000",
            },
        )

        entry_result = await trading_service.execute_instruction("BTC-USDT-SWAP", entry_instruction)
        assert entry_result.execution_result.success

        import asyncio
        await asyncio.sleep(2)

        # 获取仓位信息
        position = await trading_service.get_position("BTC-USDT-SWAP")
        balance = await trading_service.get_balance()

        # 平仓
        close_result = await trading_service.execute_instruction(
            "BTC-USDT-SWAP",
            TradeInstruction(op=TradeOperation.CLOSE_POSITION)
        )
        assert close_result.execution_result.success

        await asyncio.sleep(2)

        # 处理平仓后操作
        await trading_service.handle_position_close(
            inst_id="BTC-USDT-SWAP",
            closed_position=position,
            balance_after_close=balance,
            order_id=close_result.order_id or "test-order",
        )

        # 验证CSV文件
        with open(temp_csv_file, "r") as f:
            content = f.read()
            assert "BTC-USDT-SWAP" in content
            assert "long" in content

    async def test_client_oid_uniqueness(self, trading_service):
        """测试client_oid唯一性"""
        oids = [trading_service.generate_client_oid() for _ in range(100)]
        assert len(set(oids)) == 100  # 所有OID应该唯一


import asyncio  # noqa: E402
