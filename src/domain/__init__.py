"""领域层模块

包含交易领域模型、Agent模型、事件模型和配置数据模型。
"""

from src.domain.agent import (
    AnalystInput,
    AnalystOutput,
    CompressorInput,
    CompressorOutput,
    TraderInput,
    TraderOutput,
)
from src.domain.config import (
    Config,
    GlobalConfig,
    PromptConfig,
    TradePairConfig,
)
from src.domain.events import (
    KlineCloseEvent,
    PositionCloseEvent,
    TradeCompleteEvent,
    TradeExecutionResult,
)
from src.domain.trading import (
    Kline,
    Position,
    PositionDirection,
    TradeInstruction,
    TradeOperation,
    TradeRecord,
)

__all__ = [
    # 交易领域模型
    "Kline",
    "Position",
    "PositionDirection",
    "TradeInstruction",
    "TradeOperation",
    "TradeRecord",
    # Agent模型
    "AnalystInput",
    "AnalystOutput",
    "TraderInput",
    "TraderOutput",
    "CompressorInput",
    "CompressorOutput",
    # 事件模型
    "KlineCloseEvent",
    "TradeCompleteEvent",
    "TradeExecutionResult",
    "PositionCloseEvent",
    # 配置数据模型
    "Config",
    "GlobalConfig",
    "TradePairConfig",
    "PromptConfig",
]
