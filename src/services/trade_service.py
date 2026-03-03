"""
交易服务
处理所有与交易相关的业务逻辑
"""

from typing import Any, Optional

from src.domain.models import (
    AccountBalance,
    Position,
    PositionDirection,
    TradeInstruction,
    TradeOperation,
    TradeRecord,
)
from src.infrastructure.config_loader import TradePairConfig
from src.infrastructure.logger import Logger
from src.infrastructure.okx_client import OKXRestClient
from src.infrastructure.utils import TradeRecordStorage


class TradeService:
    """交易服务"""

    def __init__(
        self,
        okx_client: OKXRestClient,
        trade_record_storage: TradeRecordStorage,
        logger: Logger,
    ):
        self.okx_client = okx_client
        self.trade_record_storage = trade_record_storage
        self.logger = logger

    async def initialize_position_mode(
        self, trade_pairs: list[TradePairConfig], td_mode: str
    ):
        """
        初始化持仓模式
        设置所有交易对为单向持仓模式
        """
        self.logger.info("Initializing position mode...")

        # 设置持仓模式为单向持仓
        try:
            result = await self.okx_client.set_position_mode("net")
            self.logger.info(f"Position mode set to net: {result}")
        except Exception as e:
            # 51000错误表示持仓模式已设置或无法更改，可以继续
            if "51000" in str(e):
                self.logger.warning(f"Position mode already set or cannot be changed: {e}")
                self.logger.info("Continuing with existing position mode...")
            else:
                self.logger.error(f"Failed to set position mode: {e}")
                raise

        # 为每个交易对设置杠杆
        for pair in trade_pairs:
            try:
                result = await self.okx_client.set_leverage(
                    inst_id=pair.inst_id,
                    lever=pair.leverage,
                    mgn_mode=td_mode,
                )
                self.logger.info(f"Leverage set for {pair.inst_id}: {result}")
            except Exception as e:
                self.logger.error(f"Failed to set leverage for {pair.inst_id}: {e}")
                raise

    async def get_balance(self, ccy: str = "USDT") -> AccountBalance:
        """获取账户余额"""
        data = await self.okx_client.get_balance(ccy)
        return AccountBalance.from_okx_data(data)

    async def get_position(self, inst_id: str) -> Position:
        """获取持仓信息"""
        positions = await self.okx_client.get_positions(inst_id)
        if positions:
            return Position.from_okx_data(inst_id, positions[0])
        return Position(inst_id=inst_id)

    async def execute_instruction(
        self,
        inst_id: str,
        instruction: TradeInstruction,
        td_mode: str,
        trade_pair_config: TradePairConfig,
    ) -> dict[str, Any]:
        """
        执行交易指令

        Returns:
            执行结果
        """
        self.logger.audit(
            operation=instruction.op.value,
            params={"inst_id": inst_id, "args": instruction.args},
            result={},
        )

        try:
            if instruction.op == TradeOperation.ENTRY_LONG:
                return await self._entry_long(
                    inst_id, instruction, td_mode, trade_pair_config
                )
            elif instruction.op == TradeOperation.ENTRY_SHORT:
                return await self._entry_short(
                    inst_id, instruction, td_mode, trade_pair_config
                )
            elif instruction.op == TradeOperation.CLOSE_POSITION:
                return await self._close_position(inst_id, td_mode)
            elif instruction.op == TradeOperation.CHANGE_STOP:
                return await self._change_stop(inst_id, instruction)
            elif instruction.op == TradeOperation.CHANGE_PROFIT:
                return await self._change_profit(inst_id, instruction)
            elif instruction.op == TradeOperation.EXIT_LONG:
                return await self._exit_long(inst_id, instruction, td_mode)
            elif instruction.op == TradeOperation.EXIT_SHORT:
                return await self._exit_short(inst_id, instruction, td_mode)
            else:
                raise ValueError(f"Unknown operation: {instruction.op}")

        except Exception as e:
            self.logger.error(f"Failed to execute instruction: {e}")
            raise

    async def _entry_long(
        self,
        inst_id: str,
        instruction: TradeInstruction,
        td_mode: str,
        config: TradePairConfig,
    ) -> dict[str, Any]:
        """市价开多仓"""
        size = instruction.args.get("size", 0)
        stop_price = instruction.args.get("stop_price")
        profit_price = instruction.args.get("profit_price")

        # 构建附带止盈止损参数
        attach_algo_ords = []
        if stop_price:
            attach_algo_ords.append({
                "attachAlgoId": "",
                "attachAlgoOrds": [],
                "tpTriggerPx": "",
                "tpOrdPx": "",
                "slTriggerPx": str(stop_price),
                "slOrdPx": "-1",
            })
        if profit_price:
            attach_algo_ords.append({
                "attachAlgoId": "",
                "attachAlgoOrds": [],
                "tpTriggerPx": str(profit_price),
                "tpOrdPx": "-1",
                "slTriggerPx": "",
                "slOrdPx": "",
            })

        result = await self.okx_client.place_order(
            inst_id=inst_id,
            td_mode=td_mode,
            side="buy",
            ord_type="market",
            sz=str(size),
            pos_side="long" if td_mode == "cross" else None,
            attach_algo_ords=attach_algo_ords if attach_algo_ords else None,
            client_oid=instruction.client_oid,
        )

        self.logger.info(f"Entry long order placed: {result}")
        return result

    async def _entry_short(
        self,
        inst_id: str,
        instruction: TradeInstruction,
        td_mode: str,
        config: TradePairConfig,
    ) -> dict[str, Any]:
        """市价开空仓"""
        size = instruction.args.get("size", 0)
        stop_price = instruction.args.get("stop_price")
        profit_price = instruction.args.get("profit_price")

        # 构建附带止盈止损参数
        attach_algo_ords = []
        if stop_price:
            attach_algo_ords.append({
                "attachAlgoId": "",
                "attachAlgoOrds": [],
                "tpTriggerPx": "",
                "tpOrdPx": "",
                "slTriggerPx": str(stop_price),
                "slOrdPx": "-1",
            })
        if profit_price:
            attach_algo_ords.append({
                "attachAlgoId": "",
                "attachAlgoOrds": [],
                "tpTriggerPx": str(profit_price),
                "tpOrdPx": "-1",
                "slTriggerPx": "",
                "slOrdPx": "",
            })

        result = await self.okx_client.place_order(
            inst_id=inst_id,
            td_mode=td_mode,
            side="sell",
            ord_type="market",
            sz=str(size),
            pos_side="short" if td_mode == "cross" else None,
            attach_algo_ords=attach_algo_ords if attach_algo_ords else None,
            client_oid=instruction.client_oid,
        )

        self.logger.info(f"Entry short order placed: {result}")
        return result

    async def _close_position(self, inst_id: str, td_mode: str) -> dict[str, Any]:
        """平仓"""
        result = await self.okx_client.close_position(
            inst_id=inst_id,
            mgn_mode=td_mode,
        )

        self.logger.info(f"Position closed: {result}")
        return result

    async def _change_stop(
        self, inst_id: str, instruction: TradeInstruction
    ) -> dict[str, Any]:
        """修改止损价格"""
        # 需要通过修改订单或重新下单来实现
        # 这里简化处理，实际实现可能需要更复杂的逻辑
        self.logger.info(f"Change stop price: {instruction.args}")
        return {"status": "not_implemented"}

    async def _change_profit(
        self, inst_id: str, instruction: TradeInstruction
    ) -> dict[str, Any]:
        """修改止盈价格"""
        self.logger.info(f"Change profit price: {instruction.args}")
        return {"status": "not_implemented"}

    async def _exit_long(
        self,
        inst_id: str,
        instruction: TradeInstruction,
        td_mode: str,
    ) -> dict[str, Any]:
        """减仓（多仓）"""
        size = instruction.args.get("size", 0)

        result = await self.okx_client.place_order(
            inst_id=inst_id,
            td_mode=td_mode,
            side="sell",
            ord_type="market",
            sz=str(size),
            pos_side="long" if td_mode == "cross" else None,
        )

        self.logger.info(f"Exit long order placed: {result}")
        return result

    async def _exit_short(
        self,
        inst_id: str,
        instruction: TradeInstruction,
        td_mode: str,
    ) -> dict[str, Any]:
        """减仓（空仓）"""
        size = instruction.args.get("size", 0)

        result = await self.okx_client.place_order(
            inst_id=inst_id,
            td_mode=td_mode,
            side="buy",
            ord_type="market",
            sz=str(size),
            pos_side="short" if td_mode == "cross" else None,
        )

        self.logger.info(f"Exit short order placed: {result}")
        return result

    def save_trade_record(self, record: TradeRecord):
        """保存交易记录"""
        self.trade_record_storage.append_record(record.to_dict())
        self.logger.info(f"Trade record saved: {record}")
