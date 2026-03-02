"""交易服务

实现交易指令执行、仓位管理、风险控制。
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.domain.config import TradePairConfig
from src.domain.events import PositionCloseEvent, TradeCompleteEvent, TradeExecutionResult
from src.domain.trading import Position, PositionDirection, TradeInstruction, TradeOperation, TradeRecord
from src.infrastructure.csv_storage import CSVStorage, TradeRecord as CSVTradeRecord
from src.infrastructure.logger import Logger

if TYPE_CHECKING:
    from src.infrastructure.okx_rest_client import OkxRestClient


class TradingServiceError(Exception):
    """交易服务错误"""
    pass


class TradingService:
    """交易服务

    负责交易指令执行、仓位管理、风险控制。
    """

    def __init__(
        self,
        okx_client: OkxRestClient,
        csv_storage: CSVStorage,
        trade_pairs_config: list[TradePairConfig],
        td_mode: str = "isolated",
    ) -> None:
        """初始化交易服务

        Args:
            okx_client: OKX REST客户端
            csv_storage: CSV存储器
            trade_pairs_config: 交易对配置列表
            td_mode: 交易模式（isolated/cross）
        """
        self._okx_client = okx_client
        self._csv_storage = csv_storage
        self._trade_pairs_config = {cfg.inst_id: cfg for cfg in trade_pairs_config}
        self._td_mode = td_mode
        self._logger = Logger()
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """初始化交易服务

        设置所有交易对为单向持仓模式，并设置杠杆。
        """
        self._logger.info("初始化交易服务...")

        # 设置单向持仓模式
        try:
            result = await self._okx_client.set_position_mode("net_mode")
            self._logger.info(f"持仓模式已设置为单向持仓: {result}")
        except Exception as e:
            if "51000" in str(e) or "already set" in str(e).lower():
                self._logger.info("持仓模式已经是单向持仓")
            else:
                raise TradingServiceError(f"设置持仓模式失败: {e}") from e

        # 为每个交易对设置杠杆
        for inst_id, config in self._trade_pairs_config.items():
            try:
                result = await self._okx_client.set_leverage(
                    inst_id=inst_id,
                    lever=config.leverage,
                    mgn_mode=self._td_mode,
                )
                self._logger.info(f"杠杆设置成功: {inst_id} = {config.leverage}x")
            except Exception as e:
                raise TradingServiceError(f"设置杠杆失败: {inst_id}, {e}") from e

        self._logger.info("交易服务初始化完成")

    async def get_position(self, inst_id: str) -> Position:
        """获取当前仓位

        Args:
            inst_id: 交易对ID

        Returns:
            当前仓位信息
        """
        try:
            response = await self._okx_client.get_positions(inst_id=inst_id)
            data = response.get("data", [])

            if not data:
                return Position(inst_id=inst_id)

            # 取第一个持仓（单向持仓模式只有一个）
            pos_data = data[0]
            pos_side = pos_data.get("posSide", "")
            pos_size = Decimal(str(pos_data.get("pos", "0")))
            pos_size_abs = abs(pos_size)

            if pos_size_abs == 0:
                return Position(inst_id=inst_id)

            # 根据持仓数量正负判断方向
            if pos_size > 0:
                direction = PositionDirection.LONG
            else:
                direction = PositionDirection.SHORT

            return Position(
                inst_id=inst_id,
                direction=direction,
                size=pos_size_abs,
                entry_price=Decimal(str(pos_data.get("avgPx", "0"))),
                unrealized_pnl=Decimal(str(pos_data.get("upl", "0"))),
            )

        except Exception as e:
            self._logger.error(f"获取仓位失败: {inst_id}, {e}")
            raise TradingServiceError(f"获取仓位失败: {e}") from e

    async def get_balance(self, ccy: str = "USDT") -> Decimal:
        """获取账户余额

        Args:
            ccy: 币种，默认USDT

        Returns:
            可用余额
        """
        try:
            response = await self._okx_client.get_balance(ccy=ccy)
            data = response.get("data", [])

            if not data or not data[0].get("details"):
                return Decimal("0")

            for detail in data[0]["details"]:
                if detail.get("ccy") == ccy:
                    return Decimal(str(detail.get("availBal", "0")))

            return Decimal("0")

        except Exception as e:
            self._logger.error(f"获取余额失败: {ccy}, {e}")
            raise TradingServiceError(f"获取余额失败: {e}") from e

    def _validate_instruction_params(
        self,
        instruction: TradeInstruction,
        config: TradePairConfig,
    ) -> None:
        """验证指令参数是否符合配置要求

        Args:
            instruction: 交易指令
            config: 交易对配置

        Raises:
            ValueError: 验证失败时抛出
        """
        op = instruction.op
        args = instruction.args

        if op in (TradeOperation.ENTRY_LONG, TradeOperation.ENTRY_SHORT):
            # 验证止损止盈比例
            stop_loss = Decimal(str(args.get("stop_loss", 0)))
            take_profit = Decimal(str(args.get("take_profit", 0)))
            size = Decimal(str(args.get("size", 0)))

            if size <= 0:
                raise ValueError("开仓金额必须大于0")

            if size > config.position_size:
                raise ValueError(
                    f"开仓金额 {size} 超过配置限制 {config.position_size}"
                )

            # 注意：这里只验证价格存在，具体比例在开仓时根据当前价格计算
            if stop_loss <= 0:
                raise ValueError("止损价格必须大于0")
            if take_profit <= 0:
                raise ValueError("止盈价格必须大于0")

    def _validate_instruction_against_position(
        self,
        instruction: TradeInstruction,
        position: Position,
    ) -> None:
        """验证指令与当前仓位的兼容性

        Args:
            instruction: 交易指令
            position: 当前仓位

        Raises:
            ValueError: 验证失败时抛出
        """
        op = instruction.op
        args = instruction.args

        if op in (TradeOperation.ENTRY_LONG, TradeOperation.ENTRY_SHORT):
            expected_direction = (
                PositionDirection.LONG
                if op == TradeOperation.ENTRY_LONG
                else PositionDirection.SHORT
            )
            if not position.is_empty() and position.direction != expected_direction:
                raise ValueError(
                    f"已有{position.direction.value}仓位，无法开{expected_direction.value}仓"
                )

        elif op in (TradeOperation.EXIT_LONG, TradeOperation.EXIT_SHORT):
            if position.is_empty():
                raise ValueError(f"空仓无法执行 {op.value}")

            expected_direction = (
                PositionDirection.LONG
                if op == TradeOperation.EXIT_LONG
                else PositionDirection.SHORT
            )
            if position.direction != expected_direction:
                raise ValueError(
                    f"当前为{position.direction.value}仓位，无法执行 {op.value}"
                )

            exit_size = Decimal(str(args.get("size", 0)))
            if exit_size >= position.size:
                raise ValueError(
                    f"减仓数量 {exit_size} 必须小于当前持仓 {position.size}，全平请用 close_position"
                )

        elif op in (TradeOperation.CHANGE_STOP, TradeOperation.CHANGE_PROFIT):
            if position.is_empty():
                raise ValueError(f"空仓无法执行 {op.value}")

        elif op == TradeOperation.CLOSE_POSITION:
            if position.is_empty():
                raise ValueError("空仓无法执行平仓操作")

    async def _execute_entry(
        self,
        inst_id: str,
        side: str,
        size: Decimal,
        stop_loss: Decimal,
        take_profit: Decimal,
        client_oid: str,
    ) -> dict[str, Any]:
        """执行开仓操作

        Args:
            inst_id: 交易对ID
            side: buy/sell
            size: 开仓金额
            stop_loss: 止损价格
            take_profit: 止盈价格
            client_oid: 客户端订单ID

        Returns:
            下单结果
        """
        # 获取交易对信息，计算合约张数
        self._logger.info(f"获取交易对信息: {inst_id}")
        instrument = await self._okx_client.get_instrument(inst_id, inst_type="SWAP")
        self._logger.info(f"交易对信息响应: {instrument}")

        inst_data = instrument.get("data", [{}])[0]
        ct_val = Decimal(str(inst_data.get("ctVal", "1")))
        min_sz = Decimal(str(inst_data.get("minSz", "1")))  # 最小下单数量
        ct_mult = Decimal(str(inst_data.get("ctMult", "1")))  # 合约乘数
        tick_sz = Decimal(str(inst_data.get("tickSz", "0.1")))  # 价格精度
        lot_sz = Decimal(str(inst_data.get("lotSz", "0.01")))  # 数量精度

        self._logger.info(f"交易对参数: ctVal={ct_val}, minSz={min_sz}, ctMult={ct_mult}, tickSz={tick_sz}, lotSz={lot_sz}")

        # 计算合约张数（size是USDT名义金额）
        # 需要获取当前价格来计算张数
        candles = await self._okx_client.get_candles(inst_id, "1m", limit=1)
        self._logger.info(f"K线数据响应: {candles}")

        candle_data = candles.get("data", [[]])[0]
        current_price = Decimal(str(candle_data[4])) if candle_data else Decimal("0")

        if current_price == 0:
            raise TradingServiceError("无法获取当前价格")

        # 计算合约张数
        # sz = 名义价值 / (合约面值 * 合约乘数 * 当前价格)
        sz = (size / (ct_val * ct_mult * current_price)).quantize(lot_sz)
        self._logger.info(
            f"计算合约张数: size={size}, ctVal={ct_val}, ctMult={ct_mult}, "
            f"price={current_price}, sz={sz}, minSz={min_sz}, lotSz={lot_sz}"
        )

        if sz < min_sz:
            sz = min_sz
            self._logger.info(f"合约张数低于最小限制，调整为: {sz}")

        if sz <= 0:
            raise TradingServiceError(f"计算的合约张数无效: {sz}")

        # 调整止盈止损价格精度
        stop_loss_adjusted = stop_loss.quantize(tick_sz)
        take_profit_adjusted = take_profit.quantize(tick_sz)
        self._logger.info(
            f"调整价格精度: stop_loss={stop_loss} -> {stop_loss_adjusted}, "
            f"take_profit={take_profit} -> {take_profit_adjusted}"
        )

        # 构建附带止盈止损参数
        # OKX API格式: https://www.okx.com/docs-v5/zh/#rest-api-trade-place-order
        # attachAlgoOrds 是一个列表，每个元素是一个条件单对象
        attach_algo_ords = [
            {
                "tpTriggerPx": str(take_profit_adjusted),
                "tpOrdPx": "-1",  # 市价止盈
                "slTriggerPx": str(stop_loss_adjusted),
                "slOrdPx": "-1",  # 市价止损
            }
        ]

        self._logger.info(
            f"下单参数: inst_id={inst_id}, side={side}, sz={sz}, "
            f"td_mode={self._td_mode}, client_oid={client_oid}, "
            f"attach_algo_ords={attach_algo_ords}"
        )

        result = await self._okx_client.place_order(
            inst_id=inst_id,
            side=side,
            sz=str(sz),
            ord_type="market",
            td_mode=self._td_mode,
            attach_algo_ords=attach_algo_ords,
            client_oid=client_oid,
        )

        self._logger.info(f"下单结果: {result}")
        return result

    async def _execute_close(
        self,
        inst_id: str,
        position: Position,
        client_oid: str,
    ) -> dict[str, Any]:
        """执行平仓操作

        Args:
            inst_id: 交易对ID
            position: 当前仓位
            client_oid: 客户端订单ID

        Returns:
            平仓结果
        """
        # 单向持仓模式下不需要传入posSide参数
        # 只有在双向持仓模式下才需要指定posSide
        result = await self._okx_client.close_position(
            inst_id=inst_id,
            mgn_mode=self._td_mode,
            auto_cxl=True,  # 自动撤销关联的止盈止损订单
        )

        return result

    async def _execute_exit(
        self,
        inst_id: str,
        side: str,
        size: Decimal,
        client_oid: str,
    ) -> dict[str, Any]:
        """执行减仓操作

        Args:
            inst_id: 交易对ID
            side: buy/sell（与持仓方向相反）
            size: 减仓数量
            client_oid: 客户端订单ID

        Returns:
            下单结果
        """
        # 获取交易对精度信息
        instrument = await self._okx_client.get_instrument(inst_id, inst_type="SWAP")
        inst_data = instrument.get("data", [{}])[0]
        lot_sz = Decimal(str(inst_data.get("lotSz", "0.01")))

        # 调整数量精度
        adjusted_size = size.quantize(lot_sz)
        self._logger.info(f"减仓数量调整: {size} -> {adjusted_size} (lotSz={lot_sz})")

        result = await self._okx_client.place_order(
            inst_id=inst_id,
            side=side,
            sz=str(adjusted_size),
            ord_type="market",
            td_mode=self._td_mode,
            client_oid=client_oid,
        )

        return result

    async def _execute_change_stop(
        self,
        inst_id: str,
        new_stop_price: Decimal,
    ) -> dict[str, Any]:
        """执行修改止损操作

        Args:
            inst_id: 交易对ID
            new_stop_price: 新止损价格

        Returns:
            修改结果
        """
        # 获取当前持仓的止盈止损订单
        # 注意：OKX API需要algo_id来修改条件单，这里简化处理
        # 实际实现可能需要先查询现有的algo订单
        self._logger.warning(f"修改止损功能需要实现algo订单查询: {inst_id}")
        # 暂时返回空结果，实际实现需要调用 amend_order 或 algo 相关接口
        return {"data": [], "msg": "修改止损需要实现algo订单管理"}

    async def _execute_change_profit(
        self,
        inst_id: str,
        new_profit_price: Decimal,
    ) -> dict[str, Any]:
        """执行修改止盈操作

        Args:
            inst_id: 交易对ID
            new_profit_price: 新止盈价格

        Returns:
            修改结果
        """
        self._logger.warning(f"修改止盈功能需要实现algo订单查询: {inst_id}")
        return {"data": [], "msg": "修改止盈需要实现algo订单管理"}

    async def execute_instruction(
        self,
        inst_id: str,
        instruction: TradeInstruction,
    ) -> TradeCompleteEvent:
        """执行单条交易指令

        Args:
            inst_id: 交易对ID
            instruction: 交易指令

        Returns:
            交易完成事件
        """
        async with self._lock:
            self._logger.info(
                f"执行交易指令: {inst_id}, op={instruction.op.value}, "
                f"client_oid={instruction.client_oid}"
            )

            try:
                # 获取交易对配置
                config = self._trade_pairs_config.get(inst_id)
                if not config:
                    raise TradingServiceError(f"未找到交易对配置: {inst_id}")

                # 重新查询最新仓位和余额
                position = await self.get_position(inst_id)
                balance = await self.get_balance()

                # 验证指令
                self._validate_instruction_params(instruction, config)
                self._validate_instruction_against_position(instruction, position)

                # 执行指令
                op = instruction.op
                args = instruction.args
                result: dict[str, Any] = {}
                order_id: str | None = None

                if op == TradeOperation.ENTRY_LONG:
                    result = await self._execute_entry(
                        inst_id=inst_id,
                        side="buy",
                        size=Decimal(str(args.get("size", 0))),
                        stop_loss=Decimal(str(args.get("stop_loss", 0))),
                        take_profit=Decimal(str(args.get("take_profit", 0))),
                        client_oid=instruction.client_oid,
                    )

                elif op == TradeOperation.ENTRY_SHORT:
                    result = await self._execute_entry(
                        inst_id=inst_id,
                        side="sell",
                        size=Decimal(str(args.get("size", 0))),
                        stop_loss=Decimal(str(args.get("stop_loss", 0))),
                        take_profit=Decimal(str(args.get("take_profit", 0))),
                        client_oid=instruction.client_oid,
                    )

                elif op == TradeOperation.CLOSE_POSITION:
                    result = await self._execute_close(
                        inst_id=inst_id,
                        position=position,
                        client_oid=instruction.client_oid,
                    )

                elif op == TradeOperation.EXIT_LONG:
                    # 多仓减仓，需要卖出
                    result = await self._execute_exit(
                        inst_id=inst_id,
                        side="sell",
                        size=Decimal(str(args.get("size", 0))),
                        client_oid=instruction.client_oid,
                    )

                elif op == TradeOperation.EXIT_SHORT:
                    # 空仓减仓，需要买入
                    result = await self._execute_exit(
                        inst_id=inst_id,
                        side="buy",
                        size=Decimal(str(args.get("size", 0))),
                        client_oid=instruction.client_oid,
                    )

                elif op == TradeOperation.CHANGE_STOP:
                    result = await self._execute_change_stop(
                        inst_id=inst_id,
                        new_stop_price=Decimal(str(args.get("stop_price", 0))),
                    )

                elif op == TradeOperation.CHANGE_PROFIT:
                    result = await self._execute_change_profit(
                        inst_id=inst_id,
                        new_profit_price=Decimal(str(args.get("profit_price", 0))),
                    )

                # 提取订单ID
                if result.get("data"):
                    order_data = result["data"][0] if isinstance(result["data"], list) else result["data"]
                    order_id = order_data.get("ordId") or order_data.get("ordId")

                self._logger.info(
                    f"交易指令执行成功: {inst_id}, op={op.value}, order_id={order_id}"
                )

                execution_result = TradeExecutionResult(
                    success=True,
                    order_id=order_id,
                    error_message=None,
                )

                return TradeCompleteEvent(
                    inst_id=inst_id,
                    op=op,
                    order_id=order_id,
                    execution_result=execution_result,
                    error_message=None,
                )

            except Exception as e:
                self._logger.error(
                    f"交易指令执行失败: {inst_id}, op={instruction.op.value}, error={e}"
                )

                execution_result = TradeExecutionResult(
                    success=False,
                    order_id=None,
                    error_message=str(e),
                )

                return TradeCompleteEvent(
                    inst_id=inst_id,
                    op=instruction.op,
                    order_id=None,
                    execution_result=execution_result,
                    error_message=str(e),
                )

    async def execute_instructions(
        self,
        inst_id: str,
        instructions: list[TradeInstruction],
    ) -> list[TradeCompleteEvent]:
        """批量执行交易指令

        Args:
            inst_id: 交易对ID
            instructions: 交易指令列表

        Returns:
            交易完成事件列表
        """
        results: list[TradeCompleteEvent] = []

        for instruction in instructions:
            result = await self.execute_instruction(inst_id, instruction)
            results.append(result)

            # 如果执行失败，记录错误但继续执行后续指令
            if not result.execution_result.success:
                self._logger.warning(
                    f"指令执行失败，继续执行后续指令: {inst_id}, op={instruction.op.value}"
                )

        return results

    async def handle_position_close(
        self,
        inst_id: str,
        closed_position: Position,
        balance_after_close: Decimal,
        order_id: str,
    ) -> PositionCloseEvent:
        """处理平仓后操作

        写入交易记录到CSV，触发平仓完成事件。

        Args:
            inst_id: 交易对ID
            closed_position: 平仓仓位信息
            balance_after_close: 平仓后账户余额
            order_id: 订单ID

        Returns:
            平仓完成事件
        """
        self._logger.info(f"处理平仓后操作: {inst_id}, order_id={order_id}")

        # 创建交易记录
        import time
        trade_record = TradeRecord(
            timestamp=int(time.time() * 1000),
            inst_id=inst_id,
            position_direction=closed_position.direction,
            position_size=closed_position.size,
            entry_avg_price=closed_position.entry_price,
            exit_avg_price=Decimal("0"),  # 需要从订单详情获取
            realized_pnl=closed_position.unrealized_pnl,
            balance_after_close=balance_after_close,
            order_id=order_id,
        )

        # 写入CSV
        csv_record = CSVTradeRecord(
            timestamp=str(trade_record.timestamp),
            inst_id=trade_record.inst_id,
            position_direction=trade_record.position_direction.value,
            position_size=str(trade_record.position_size),
            entry_avg_price=str(trade_record.entry_avg_price),
            exit_avg_price=str(trade_record.exit_avg_price),
            realized_pnl=str(trade_record.realized_pnl),
            balance_after_close=str(trade_record.balance_after_close),
            order_id=trade_record.order_id,
        )
        await self._csv_storage.append(csv_record)

        self._logger.info(f"交易记录已写入CSV: {inst_id}, order_id={order_id}")

        return PositionCloseEvent(
            inst_id=inst_id,
            closed_position=closed_position,
            balance_after_close=balance_after_close,
            trade_record=trade_record,
        )

    def generate_client_oid(self) -> str:
        """生成客户端订单ID

        OKX要求clOrdId长度不超过32个字符。

        Returns:
            32字符以内的客户端订单ID
        """
        # 使用UUID前32个字符（去掉连字符）
        return str(uuid4()).replace("-", "")[:32]
