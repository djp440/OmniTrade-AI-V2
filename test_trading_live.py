"""交易服务实时测试脚本

在OKX模拟盘环境测试交易服务，查看详细日志。
"""

from __future__ import annotations

import asyncio
import logging
import os
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 加载.env文件
env_path = Path(__file__).parent / "config" / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"已加载环境变量: {env_path}")
else:
    print(f"警告: 未找到.env文件: {env_path}")

from src.infrastructure.okx_auth import OkxCredentials
from src.infrastructure.okx_rest_client import OkxRestClient
from src.infrastructure.csv_storage import CSVStorage
from src.domain.config import TradePairConfig
from src.domain.trading import TradeInstruction, TradeOperation, PositionDirection
from src.services.trading_service import TradingService


async def test_trading():
    """测试交易功能"""
    print("=" * 60)
    print("交易服务实时测试")
    print("=" * 60)

    # 从环境变量加载API密钥
    api_key = os.getenv("OKX_DEMO_API_KEY", "")
    api_secret = os.getenv("OKX_DEMO_API_SECRET", "")
    passphrase = os.getenv("OKX_DEMO_PASSPHRASE", "")

    if not all([api_key, api_secret, passphrase]):
        print("错误: 未配置OKX模拟盘API密钥")
        print("请设置环境变量: OKX_DEMO_API_KEY, OKX_DEMO_API_SECRET, OKX_DEMO_PASSPHRASE")
        return

    print(f"API Key: {api_key[:10]}...")

    # 创建OKX客户端（模拟盘）
    credentials = OkxCredentials(
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
    )
    okx_client = OkxRestClient(credentials, is_simulated=True)

    # 创建交易服务
    csv_storage = CSVStorage("./test_trade_records.csv")
    trade_config = TradePairConfig(
        inst_id="BTC-USDT-SWAP",
        timeframe="1H",
        leverage=10,
        position_size=Decimal("100"),  # 使用100 USDT测试
        stop_loss_ratio=Decimal("0.02"),
        take_profit_ratio=Decimal("0.05"),
    )

    service = TradingService(
        okx_client=okx_client,
        csv_storage=csv_storage,
        trade_pairs_config=[trade_config],
        td_mode="cross",
    )

    try:
        # 步骤1: 初始化
        print("\n[步骤1] 初始化交易服务...")
        await service.initialize()
        print("✓ 初始化成功")

        # 步骤2: 查询余额
        print("\n[步骤2] 查询账户余额...")
        balance = await service.get_balance("USDT")
        print(f"✓ 当前USDT余额: {balance}")

        # 步骤3: 查询当前仓位
        print("\n[步骤3] 查询当前仓位...")
        position = await service.get_position("BTC-USDT-SWAP")
        print(f"✓ 当前仓位: {position}")
        print(f"  - 方向: {position.direction.value}")
        print(f"  - 数量: {position.size}")
        print(f"  - 开仓均价: {position.entry_price}")

        # 如果已有仓位，先平仓
        if not position.is_empty():
            print("\n[步骤3.5] 检测到已有仓位，先平仓...")
            close_instruction = TradeInstruction(op=TradeOperation.CLOSE_POSITION)
            close_result = await service.execute_instruction("BTC-USDT-SWAP", close_instruction)
            print(f"✓ 平仓结果: {close_result.execution_result}")
            await asyncio.sleep(2)

        # 步骤4: 获取当前价格
        print("\n[步骤4] 获取当前价格...")
        candles = await okx_client.get_candles("BTC-USDT-SWAP", "1m", limit=1)
        current_price = Decimal(str(candles["data"][0][4]))
        print(f"✓ 当前BTC价格: {current_price} USDT")

        # 步骤5: 计算止损止盈价格
        print("\n[步骤5] 计算止损止盈价格...")
        stop_loss = current_price * Decimal("0.98")  # 2% 止损
        take_profit = current_price * Decimal("1.05")  # 5% 止盈
        print(f"  - 止损价格: {stop_loss} (2%)")
        print(f"  - 止盈价格: {take_profit} (5%)")

        # 步骤6: 执行开多仓
        print("\n[步骤6] 执行开多仓...")
        instruction = TradeInstruction(
            op=TradeOperation.ENTRY_LONG,
            args={
                "size": "100",
                "stop_loss": str(stop_loss),
                "take_profit": str(take_profit),
            },
        )

        result = await service.execute_instruction("BTC-USDT-SWAP", instruction)
        print(f"✓ 执行结果:")
        print(f"  - 成功: {result.execution_result.success}")
        print(f"  - 订单ID: {result.order_id}")
        print(f"  - 错误信息: {result.execution_result.error_message}")

        if not result.execution_result.success:
            print(f"\n✗ 开仓失败，停止测试")
            return

        # 步骤7: 等待订单处理并查询仓位
        print("\n[步骤7] 等待2秒后查询仓位...")
        await asyncio.sleep(2)
        position = await service.get_position("BTC-USDT-SWAP")
        print(f"✓ 开仓后仓位:")
        print(f"  - 方向: {position.direction.value}")
        print(f"  - 数量: {position.size}")
        print(f"  - 开仓均价: {position.entry_price}")

        if position.is_empty():
            print("\n✗ 警告: 仓位为空，可能开仓失败")
            return

        # 步骤8: 执行部分减仓
        print("\n[步骤8] 执行部分减仓 (减仓50%)...")
        exit_size = position.size / 2
        exit_instruction = TradeInstruction(
            op=TradeOperation.EXIT_LONG,
            args={"size": str(exit_size)},
        )
        exit_result = await service.execute_instruction("BTC-USDT-SWAP", exit_instruction)
        print(f"✓ 减仓结果:")
        print(f"  - 成功: {exit_result.execution_result.success}")
        print(f"  - 订单ID: {exit_result.order_id}")

        await asyncio.sleep(2)

        # 步骤9: 查询减仓后的仓位
        print("\n[步骤9] 查询减仓后的仓位...")
        position = await service.get_position("BTC-USDT-SWAP")
        print(f"✓ 减仓后仓位:")
        print(f"  - 方向: {position.direction.value}")
        print(f"  - 数量: {position.size}")

        # 步骤10: 全平
        print("\n[步骤10] 执行全平...")
        close_instruction = TradeInstruction(op=TradeOperation.CLOSE_POSITION)
        close_result = await service.execute_instruction("BTC-USDT-SWAP", close_instruction)
        print(f"✓ 平仓结果:")
        print(f"  - 成功: {close_result.execution_result.success}")
        print(f"  - 订单ID: {close_result.order_id}")

        await asyncio.sleep(2)

        # 步骤11: 验证仓位已清空
        print("\n[步骤11] 验证仓位已清空...")
        position = await service.get_position("BTC-USDT-SWAP")
        if position.is_empty():
            print("✓ 仓位已清空")
        else:
            print(f"✗ 警告: 仓位未清空: {position}")

        # 步骤12: 查询最终余额
        print("\n[步骤12] 查询最终余额...")
        final_balance = await service.get_balance("USDT")
        print(f"✓ 最终USDT余额: {final_balance}")
        print(f"  - 盈亏: {final_balance - balance}")

        print("\n" + "=" * 60)
        print("测试完成!")
        print("=" * 60)
        print("请登录OKX模拟盘查看订单和仓位记录:")
        print("https://www.okx.com/trade-swap/demo/btc-usdt-swap")

    except Exception as e:
        print(f"\n✗ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await okx_client.close()


if __name__ == "__main__":
    asyncio.run(test_trading())
