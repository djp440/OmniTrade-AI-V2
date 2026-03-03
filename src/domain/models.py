"""
领域模型
包含交易领域模型、Agent模型、事件模型
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


class PositionDirection(Enum):
    """持仓方向"""

    EMPTY = "empty"
    LONG = "long"
    SHORT = "short"


class TradeOperation(Enum):
    """交易操作类型"""

    ENTRY_LONG = "entry_long"
    ENTRY_SHORT = "entry_short"
    CLOSE_POSITION = "close_position"
    CHANGE_STOP = "change_stop"
    CHANGE_PROFIT = "change_profit"
    EXIT_LONG = "exit_long"
    EXIT_SHORT = "exit_short"


@dataclass
class Kline:
    """K线模型"""

    timestamp: int
    open: float
    high: float
    low: float
    close: float
    vol: float
    confirm: int = 0

    @classmethod
    def from_okx_data(cls, data: list) -> "Kline":
        """从OKX数据创建Kline对象"""
        return cls(
            timestamp=int(data[0]),
            open=float(data[1]),
            high=float(data[2]),
            low=float(data[3]),
            close=float(data[4]),
            vol=float(data[5]),
            confirm=int(data[8]) if len(data) > 8 else 0,
        )


@dataclass
class Position:
    """仓位模型"""

    inst_id: str
    direction: PositionDirection = PositionDirection.EMPTY
    size: float = 0.0
    entry_price: float = 0.0
    stop_price: Optional[float] = None
    profit_price: Optional[float] = None
    unrealized_pnl: float = 0.0

    @property
    def is_empty(self) -> bool:
        """是否空仓"""
        return self.direction == PositionDirection.EMPTY or self.size == 0

    @classmethod
    def from_okx_data(cls, inst_id: str, data: Optional[dict]) -> "Position":
        """从OKX数据创建Position对象"""
        if not data:
            return cls(inst_id=inst_id)

        pos_side = data.get("posSide", "")
        pos = data.get("pos", "0")

        if pos_side == "long" or (pos_side == "net" and float(pos) > 0):
            direction = PositionDirection.LONG
        elif pos_side == "short" or (pos_side == "net" and float(pos) < 0):
            direction = PositionDirection.SHORT
        else:
            direction = PositionDirection.EMPTY

        return cls(
            inst_id=inst_id,
            direction=direction,
            size=abs(float(pos)),
            entry_price=float(data.get("avgPx", 0) or 0),
            unrealized_pnl=float(data.get("upl", 0) or 0),
        )


@dataclass
class TradeInstruction:
    """交易指令模型"""

    op: TradeOperation
    args: dict[str, Any] = field(default_factory=dict)
    client_oid: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "op": self.op.value,
            "args": self.args,
            "client_oid": self.client_oid,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TradeInstruction":
        """从字典创建"""
        return cls(
            op=TradeOperation(data.get("op", "")),
            args=data.get("args", {}),
            client_oid=data.get("client_oid", str(uuid4())),
        )


@dataclass
class TradeRecord:
    """交易记录模型"""

    timestamp: str
    inst_id: str
    position_direction: str
    position_size: float
    entry_avg_price: float
    exit_avg_price: float
    realized_pnl: float
    balance_after_close: float
    order_id: str

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "timestamp": self.timestamp,
            "inst_id": self.inst_id,
            "position_direction": self.position_direction,
            "position_size": self.position_size,
            "entry_avg_price": self.entry_avg_price,
            "exit_avg_price": self.exit_avg_price,
            "realized_pnl": self.realized_pnl,
            "balance_after_close": self.balance_after_close,
            "order_id": self.order_id,
        }


@dataclass
class AccountBalance:
    """账户余额模型"""

    currency: str
    available: float
    frozen: float
    equity: float

    @classmethod
    def from_okx_data(cls, data: dict) -> "AccountBalance":
        """从OKX数据创建AccountBalance对象"""
        details = data.get("details", [])
        if not details:
            return cls(currency="USDT", available=0.0, frozen=0.0, equity=0.0)

        detail = details[0]
        return cls(
            currency=detail.get("ccy", "USDT"),
            available=float(detail.get("availBal", 0) or 0),
            frozen=float(detail.get("frozenBal", 0) or 0),
            equity=float(detail.get("eq", 0) or 0),
        )


# ========== Agent模型 ==========


@dataclass
class AnalystInput:
    """分析师输入"""

    kline_image_base64: str
    analysis_history: list[str]
    current_position: Position
    account_balance: AccountBalance
    trade_pair_config: dict[str, Any]
    current_time: str


@dataclass
class AnalystOutput:
    """分析师输出"""

    analysis: str
    direction: str
    stop_price: Optional[float] = None
    profit_price: Optional[float] = None
    confidence: float = 0.0


@dataclass
class TraderInput:
    """交易员输入"""

    analyst_output: AnalystOutput
    current_position: Position
    account_balance: AccountBalance
    current_price: float
    risk_per_trade: float
    trade_pair_config: dict[str, Any]


@dataclass
class TraderOutput:
    """交易员输出"""

    instructions: list[TradeInstruction]


@dataclass
class CompressorInput:
    """压缩者输入"""

    analyst_output: AnalystOutput


@dataclass
class CompressorOutput:
    """压缩者输出"""

    compressed_text: str


# ========== 事件模型 ==========


@dataclass
class KlineCloseEvent:
    """K线收盘事件"""

    inst_id: str
    timeframe: str
    kline: Kline


@dataclass
class TradeCompleteEvent:
    """交易完成事件"""

    inst_id: str
    op: TradeOperation
    order_id: str
    result: dict[str, Any]
    error: Optional[str] = None


@dataclass
class PositionCloseEvent:
    """平仓完成事件"""

    inst_id: str
    position: Position
    balance_after_close: float
    realized_pnl: float
