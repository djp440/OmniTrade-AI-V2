"""事件模型

包含K线收盘事件、交易完成事件、平仓完成事件等异步事件模型。
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from src.domain.trading import Kline, Position, TradeOperation, TradeRecord


class KlineCloseEvent(BaseModel):
    """K线收盘事件

    当OKX WebSocket推送confirm=1的K线时触发。
    """
    model_config = ConfigDict(frozen=True)

    inst_id: str = Field(..., description="交易对ID")
    timeframe: str = Field(..., description="K线周期")
    kline: Kline = Field(..., description="收盘K线数据")


class TradeExecutionResult(BaseModel):
    """交易执行结果"""
    model_config = ConfigDict(frozen=True)

    success: bool = Field(..., description="是否成功")
    order_id: str | None = Field(default=None, description="订单ID")
    error_message: str | None = Field(default=None, description="错误信息")


class TradeCompleteEvent(BaseModel):
    """交易完成事件

    当交易指令执行完成时触发。
    """
    model_config = ConfigDict(frozen=True)

    inst_id: str = Field(..., description="交易对ID")
    op: TradeOperation = Field(..., description="操作类型")
    order_id: str | None = Field(default=None, description="订单ID")
    execution_result: TradeExecutionResult = Field(..., description="执行结果")
    error_message: str | None = Field(default=None, description="错误信息")


class PositionCloseEvent(BaseModel):
    """平仓完成事件

    当仓位完全平仓后触发。
    """
    model_config = ConfigDict(frozen=True)

    inst_id: str = Field(..., description="交易对ID")
    closed_position: Position = Field(..., description="平仓仓位信息")
    balance_after_close: Decimal = Field(..., description="平仓后账户余额")
    trade_record: TradeRecord = Field(..., description="交易记录")
