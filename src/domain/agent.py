"""Agent模型

包含分析师、交易员、压缩者的输入/输出模型。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.trading import Position, TradeInstruction, TradeOperation


class AnalystInput(BaseModel):
    """分析师Agent输入模型"""
    model_config = ConfigDict(frozen=True)

    inst_id: str = Field(..., description="交易对ID")
    timeframe: str = Field(..., description="K线周期")
    kline_image_base64: str = Field(..., description="K线图base64编码")
    analysis_history: list[str] = Field(default_factory=list, description="历史分析记录")
    current_position: Position = Field(..., description="当前仓位")
    account_balance: Decimal = Field(..., description="账户余额")
    current_time: Any = Field(default=None, description="当前时间")


class AnalystOutput(BaseModel):
    """分析师Agent输出模型"""
    model_config = ConfigDict(frozen=True)

    analysis: str = Field(..., description="分析结果")
    trading_decision: str = Field(..., description="交易决策建议")


class TraderInput(BaseModel):
    """交易员Agent输入模型"""
    model_config = ConfigDict(frozen=True)

    analyst_output: str = Field(..., description="分析师输出")
    current_position: Position = Field(..., description="当前仓位")
    account_balance: Decimal = Field(..., description="账户余额")
    current_price: Decimal = Field(..., description="当前价格")
    risk_per_trade: Decimal = Field(..., description="单笔风险百分比")
    inst_id: str = Field(..., description="交易对ID")


class TraderOutput(BaseModel):
    """交易员Agent输出模型

    输出必须是严格符合JSON Schema的交易指令数组。
    """
    model_config = ConfigDict(frozen=True)

    instructions: list[TradeInstruction] = Field(default_factory=list, description="交易指令列表")

    @classmethod
    def get_json_schema(cls) -> dict[str, Any]:
        """获取交易员输出的JSON Schema"""
        return {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": [
                            "entry_long",
                            "entry_short",
                            "close_position",
                            "change_stop",
                            "change_profit",
                            "exit_long",
                            "exit_short",
                        ],
                    },
                    "args": {
                        "type": "object",
                        "properties": {
                            "size": {"type": "number"},
                            "stop_loss": {"type": "number"},
                            "take_profit": {"type": "number"},
                            "stop_price": {"type": "number"},
                            "profit_price": {"type": "number"},
                        },
                    },
                    "client_oid": {"type": "string"},
                },
                "required": ["op"],
            },
        }

    @classmethod
    def from_json(cls, data: list[dict]) -> Self:
        """从JSON数据解析交易员输出

        Args:
            data: JSON数组格式的交易指令列表

        Returns:
            TraderOutput对象

        Raises:
            ValueError: JSON格式不合法时抛出
        """
        if not isinstance(data, list):
            raise ValueError("交易员输出必须是JSON数组")

        instructions = []
        for item in data:
            if not isinstance(item, dict):
                raise ValueError(f"指令项必须是对象: {item}")

            op_str = item.get("op")
            if op_str is None:
                raise ValueError(f"指令缺少 op 字段: {item}")

            try:
                op = TradeOperation(op_str)
            except ValueError as e:
                raise ValueError(f"无效的操作类型: {op_str}") from e

            # 生成client_oid（最多32字符）
            raw_oid = item.get("client_oid", str(uuid4()))
            client_oid = raw_oid.replace("-", "")[:32]

            instruction = TradeInstruction(
                op=op,
                args=item.get("args", {}),
                client_oid=client_oid,
            )
            instructions.append(instruction)

        return cls(instructions=instructions)


class CompressorInput(BaseModel):
    """压缩者Agent输入模型"""
    model_config = ConfigDict(frozen=True)

    analyst_output: str = Field(..., description="分析师输出")


class CompressorOutput(BaseModel):
    """压缩者Agent输出模型"""
    model_config = ConfigDict(frozen=True)

    compressed_text: str = Field(..., description="压缩后的文本（不超过100字）")

    @field_validator("compressed_text")
    @classmethod
    def validate_length(cls, v: str) -> str:
        """验证压缩文本长度不超过100字"""
        if len(v) > 100:
            raise ValueError(f"压缩文本长度不能超过100字，当前{len(v)}字")
        return v
