"""交易领域模型

包含K线、仓位、交易指令、交易记录等交易相关模型。
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PositionDirection(str, Enum):
    """仓位方向枚举"""
    LONG = "long"
    SHORT = "short"
    EMPTY = "empty"


class TradeOperation(str, Enum):
    """交易操作类型枚举"""
    ENTRY_LONG = "entry_long"           # 市价开多仓（附带止盈止损）
    ENTRY_SHORT = "entry_short"         # 市价开空仓（附带止盈止损）
    CLOSE_POSITION = "close_position"   # 全平并自动取消止盈止损
    CHANGE_STOP = "change_stop"         # 修改止损价
    CHANGE_PROFIT = "change_profit"     # 修改止盈价
    EXIT_LONG = "exit_long"             # 仅减仓（多仓）
    EXIT_SHORT = "exit_short"           # 仅减仓（空仓）


class Kline(BaseModel):
    """K线模型

    表示一根K线数据，包含OHLC价格和成交量信息。

    Attributes:
        timestamp: K线时间戳（毫秒）
        open: 开盘价
        high: 最高价
        low: 最低价
        close: 收盘价
        vol: 成交量
        confirm: 是否收盘（1表示已收盘，0表示未收盘）
    """
    model_config = ConfigDict(frozen=True)

    timestamp: int = Field(..., description="K线时间戳（毫秒）")
    open: Decimal = Field(..., description="开盘价")
    high: Decimal = Field(..., description="最高价")
    low: Decimal = Field(..., description="最低价")
    close: Decimal = Field(..., description="收盘价")
    vol: Decimal = Field(..., description="成交量")
    confirm: int = Field(default=1, description="是否收盘（1=已收盘，0=未收盘）")

    @field_validator("high")
    @classmethod
    def validate_high(cls, v: Decimal, info) -> Decimal:
        """验证最高价不小于最低价"""
        data = info.data
        if "low" in data and v < data["low"]:
            raise ValueError("最高价不能小于最低价")
        return v

    @field_validator("low")
    @classmethod
    def validate_low(cls, v: Decimal, info) -> Decimal:
        """验证最低价不大于最高价"""
        data = info.data
        if "high" in data and v > data["high"]:
            raise ValueError("最低价不能大于最高价")
        return v

    @field_validator("open", "high", "low", "close", "vol")
    @classmethod
    def validate_positive(cls, v: Decimal) -> Decimal:
        """验证价格字段为正数"""
        if v < 0:
            raise ValueError("价格字段不能为负数")
        return v

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，Decimal转为字符串保证精度"""
        return {
            "timestamp": self.timestamp,
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "vol": str(self.vol),
            "confirm": self.confirm,
        }

    @classmethod
    def from_okx_data(cls, data: list) -> Self:
        """从OKX API返回的数据创建K线对象

        OKX K线数据格式: [timestamp, open, high, low, close, vol, confirm]
        """
        return cls(
            timestamp=int(data[0]),
            open=Decimal(str(data[1])),
            high=Decimal(str(data[2])),
            low=Decimal(str(data[3])),
            close=Decimal(str(data[4])),
            vol=Decimal(str(data[5])),
            confirm=int(data[6]) if len(data) > 6 else 1,
        )


class Position(BaseModel):
    """仓位模型

    表示当前持仓状态。

    Attributes:
        inst_id: 交易对ID（如 BTC-USDT-SWAP）
        direction: 仓位方向（long/short/empty）
        size: 持仓数量（合约张数）
        entry_price: 开仓均价
        stop_price: 当前止损价
        profit_price: 当前止盈价
        unrealized_pnl: 未实现盈亏
    """
    model_config = ConfigDict(frozen=True)

    inst_id: str = Field(..., description="交易对ID")
    direction: PositionDirection = Field(default=PositionDirection.EMPTY, description="仓位方向")
    size: Decimal = Field(default=Decimal("0"), description="持仓数量")
    entry_price: Decimal = Field(default=Decimal("0"), description="开仓均价")
    stop_price: Decimal | None = Field(default=None, description="当前止损价")
    profit_price: Decimal | None = Field(default=None, description="当前止盈价")
    unrealized_pnl: Decimal = Field(default=Decimal("0"), description="未实现盈亏")

    @field_validator("size")
    @classmethod
    def validate_size(cls, v: Decimal) -> Decimal:
        """验证持仓数量非负"""
        if v < 0:
            raise ValueError("持仓数量不能为负数")
        return v

    @model_validator(mode="after")
    def validate_position_consistency(self) -> Self:
        """验证仓位一致性"""
        if self.direction == PositionDirection.EMPTY:
            if self.size != 0:
                raise ValueError("空仓时持仓数量必须为0")
        else:
            if self.size == 0:
                raise ValueError("持仓方向非空时，持仓数量必须大于0")
        return self

    def is_empty(self) -> bool:
        """判断是否为空仓"""
        return self.direction == PositionDirection.EMPTY or self.size == 0

    def to_display_string(self) -> str:
        """转换为显示字符串"""
        if self.is_empty():
            return "空仓"
        return f"{self.direction.value} {self.size} @ {self.entry_price}"


class TradeInstruction(BaseModel):
    """交易指令模型

    表示一条具体的交易指令。

    Attributes:
        op: 操作类型
        args: 操作参数
        client_oid: 客户端订单ID（UUID，用于幂等性）
    """
    model_config = ConfigDict(frozen=True)

    op: TradeOperation = Field(..., description="操作类型")
    args: dict[str, Any] = Field(default_factory=dict, description="操作参数")
    client_oid: str = Field(default_factory=lambda: str(uuid4()).replace("-", "")[:32], description="客户端订单ID（最多32字符）")

    @model_validator(mode="after")
    def validate_instruction(self) -> Self:
        """验证交易指令参数合法性"""
        op = self.op
        args = self.args

        if op in (TradeOperation.ENTRY_LONG, TradeOperation.ENTRY_SHORT):
            # 开仓必须带止损止盈参数
            if "stop_loss" not in args:
                raise ValueError(f"{op.value} 必须指定 stop_loss 参数")
            if "take_profit" not in args:
                raise ValueError(f"{op.value} 必须指定 take_profit 参数")
            if "size" not in args:
                raise ValueError(f"{op.value} 必须指定 size 参数")

            # 验证价格参数为正数
            for key in ("stop_loss", "take_profit", "size"):
                value = Decimal(str(args.get(key, 0)))
                if value <= 0:
                    raise ValueError(f"{key} 必须为正数")

        elif op in (TradeOperation.EXIT_LONG, TradeOperation.EXIT_SHORT):
            # 减仓必须指定数量
            if "size" not in args:
                raise ValueError(f"{op.value} 必须指定 size 参数")
            size = Decimal(str(args["size"]))
            if size <= 0:
                raise ValueError("减仓数量必须为正数")

        elif op in (TradeOperation.CHANGE_STOP, TradeOperation.CHANGE_PROFIT):
            # 修改止损止盈必须指定新价格
            price_key = "stop_price" if op == TradeOperation.CHANGE_STOP else "profit_price"
            if price_key not in args:
                raise ValueError(f"{op.value} 必须指定 {price_key} 参数")
            price = Decimal(str(args[price_key]))
            if price <= 0:
                raise ValueError(f"{price_key} 必须为正数")

        # close_position 不需要额外参数
        return self

    def validate_against_position(
        self,
        position: Position,
        position_size_limit: Decimal | None = None,
    ) -> None:
        """验证指令与当前仓位的兼容性

        Args:
            position: 当前仓位
            position_size_limit: 仓位大小限制（用于开仓验证）

        Raises:
            ValueError: 验证失败时抛出
        """
        op = self.op

        if op in (TradeOperation.ENTRY_LONG, TradeOperation.ENTRY_SHORT):
            # 开仓时仓位必须为空或同方向
            expected_direction = (
                PositionDirection.LONG if op == TradeOperation.ENTRY_LONG else PositionDirection.SHORT
            )
            if not position.is_empty() and position.direction != expected_direction:
                raise ValueError(f"已有{position.direction.value}仓位，无法开{expected_direction.value}仓")

            # 验证开仓金额不超过限制
            if position_size_limit is not None:
                entry_size = Decimal(str(self.args.get("size", 0)))
                if entry_size > position_size_limit:
                    raise ValueError(f"开仓金额 {entry_size} 超过限制 {position_size_limit}")

        elif op in (TradeOperation.EXIT_LONG, TradeOperation.EXIT_SHORT):
            # 减仓必须持有对应方向仓位
            expected_direction = (
                PositionDirection.LONG if op == TradeOperation.EXIT_LONG else PositionDirection.SHORT
            )
            if position.is_empty():
                raise ValueError(f"空仓无法执行 {op.value}")
            if position.direction != expected_direction:
                raise ValueError(f"当前为{position.direction.value}仓位，无法执行 {op.value}")

            # 减仓数量必须小于当前持仓
            exit_size = Decimal(str(self.args.get("size", 0)))
            if exit_size >= position.size:
                raise ValueError(
                    f"减仓数量 {exit_size} 必须小于当前持仓 {position.size}，全平请用 close_position"
                )

        elif op in (TradeOperation.CHANGE_STOP, TradeOperation.CHANGE_PROFIT):
            # 修改止损止盈必须持有仓位
            if position.is_empty():
                raise ValueError(f"空仓无法执行 {op.value}")

        elif op == TradeOperation.CLOSE_POSITION:
            # 平仓必须持有仓位
            if position.is_empty():
                raise ValueError("空仓无法执行平仓操作")


class TradeRecord(BaseModel):
    """交易记录模型

    记录一次完整的平仓交易。

    Attributes:
        timestamp: 交易时间戳（毫秒）
        inst_id: 交易对ID
        position_direction: 原仓位方向
        position_size: 持仓数量
        entry_avg_price: 开仓均价
        exit_avg_price: 平仓均价
        realized_pnl: 已实现盈亏
        balance_after_close: 平仓后账户余额
        order_id: 订单ID
    """
    model_config = ConfigDict(frozen=True)

    timestamp: int = Field(..., description="交易时间戳（毫秒）")
    inst_id: str = Field(..., description="交易对ID")
    position_direction: PositionDirection = Field(..., description="原仓位方向")
    position_size: Decimal = Field(..., description="持仓数量")
    entry_avg_price: Decimal = Field(..., description="开仓均价")
    exit_avg_price: Decimal = Field(..., description="平仓均价")
    realized_pnl: Decimal = Field(..., description="已实现盈亏")
    balance_after_close: Decimal = Field(..., description="平仓后账户余额")
    order_id: str = Field(..., description="订单ID")

    def to_csv_row(self) -> dict[str, str]:
        """转换为CSV行数据"""
        from datetime import datetime
        return {
            "timestamp": str(self.timestamp),
            "datetime": datetime.fromtimestamp(self.timestamp / 1000).isoformat(),
            "inst_id": self.inst_id,
            "position_direction": self.position_direction.value,
            "position_size": str(self.position_size),
            "entry_avg_price": str(self.entry_avg_price),
            "exit_avg_price": str(self.exit_avg_price),
            "realized_pnl": str(self.realized_pnl),
            "balance_after_close": str(self.balance_after_close),
            "order_id": self.order_id,
        }

    @classmethod
    def get_csv_headers(cls) -> list[str]:
        """获取CSV表头"""
        return [
            "timestamp",
            "datetime",
            "inst_id",
            "position_direction",
            "position_size",
            "entry_avg_price",
            "exit_avg_price",
            "realized_pnl",
            "balance_after_close",
            "order_id",
        ]
