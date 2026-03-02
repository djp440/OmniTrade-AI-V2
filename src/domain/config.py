"""配置数据模型

包含全局配置、交易对配置、Prompt配置等配置相关模型。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TradePairConfig(BaseModel):
    """交易对配置模型"""
    model_config = ConfigDict(frozen=True)

    inst_id: str = Field(..., description="交易对ID（如 BTC-USDT-SWAP）")
    timeframe: str = Field(..., description="K线周期（1m/5m/15m/1H/4H/1D等）")
    leverage: int = Field(default=10, ge=1, le=125, description="杠杆倍数")
    position_size: Decimal = Field(..., gt=0, description="开仓名义金额（USDT）")
    stop_loss_ratio: Decimal = Field(..., gt=0, lt=1, description="止损比例")
    take_profit_ratio: Decimal = Field(..., gt=0, description="止盈比例")


class GlobalConfig(BaseModel):
    """全局配置模型"""
    model_config = ConfigDict(frozen=True)

    demo_mode: bool = Field(default=True, description="模拟盘开关")
    log_level: str = Field(default="INFO", description="日志级别")
    log_dir: str = Field(default="./logs", description="日志目录")
    max_analysis_history_length: int = Field(default=10, ge=1, description="分析历史最大保留条数")
    k_line_count: int = Field(default=100, ge=1, description="每次获取的历史K线数量")
    llm_model: str = Field(..., description="LLM模型名称")
    trade_record_path: str = Field(default="./trade_records.csv", description="交易记录文件路径")
    td_mode: Literal["isolated", "cross"] = Field(default="isolated", description="持仓模式")


class Config(BaseModel):
    """完整配置模型"""
    model_config = ConfigDict(frozen=True)

    global_config: GlobalConfig = Field(..., description="全局配置")
    trade_pairs: list[TradePairConfig] = Field(..., min_length=1, description="交易对配置列表")


class PromptConfig(BaseModel):
    """Prompt配置模型"""
    model_config = ConfigDict(frozen=True)

    analyst_system_prompt: str = Field(..., alias="analyst", description="分析师System Prompt")
    trader_system_prompt: str = Field(..., alias="trader", description="交易员System Prompt")
    compressor_system_prompt: str = Field(..., alias="compressor", description="压缩者System Prompt")

    def format_analyst_prompt(
        self,
        inst_id: str,
        timeframe: str,
        position: str,
        balance: Decimal,
        history: str,
    ) -> str:
        """格式化分析师Prompt"""
        return self.analyst_system_prompt.format(
            inst_id=inst_id,
            timeframe=timeframe,
            position=position,
            balance=balance,
            history=history,
        )

    def format_trader_prompt(
        self,
        inst_id: str,
        position: str,
        balance: Decimal,
        position_size: Decimal,
    ) -> str:
        """格式化交易员Prompt"""
        return self.trader_system_prompt.format(
            inst_id=inst_id,
            position=position,
            balance=balance,
            position_size=position_size,
        )
