"""
Agent调度服务
处理所有Agent的调用和协调
"""

import asyncio
import json
from typing import Any

from src.domain.models import (
    AnalystInput,
    AnalystOutput,
    CompressorInput,
    CompressorOutput,
    TradeInstruction,
    TraderInput,
    TraderOutput,
)
from src.infrastructure.config_loader import TradePairConfig
from src.infrastructure.llm_client import LLMClient
from src.infrastructure.logger import Logger


class AgentService:
    """Agent调度服务"""

    MAX_TRADER_RETRIES = 3

    def __init__(
        self,
        llm_client: LLMClient,
        prompts: dict[str, str],
        logger: Logger,
    ):
        self.llm_client = llm_client
        self.prompts = prompts
        self.logger = logger

    async def call_analyst(self, input_data: AnalystInput) -> AnalystOutput:
        """
        调用分析师Agent

        Args:
            input_data: 分析师输入数据

        Returns:
            分析师输出
        """
        system_prompt = self.prompts.get("analyst", "")

        # 构建用户消息
        user_message = self._build_analyst_message(input_data)

        self.logger.info(f"调用分析师 {input_data.current_position.inst_id}")

        response = await self.llm_client.chat(
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=0.0,
            images=[input_data.kline_image_base64],
        )

        self.logger.debug(f"分析师响应: {response}")

        # 解析分析师输出
        return self._parse_analyst_response(response)

    def _build_analyst_message(self, input_data: AnalystInput) -> str:
        """构建分析师用户消息"""
        lines = [
            f"Current Time: {input_data.current_time}",
            f"Trading Pair: {input_data.current_position.inst_id}",
            "",
            "Account Balance:",
            f"  - Available: {input_data.account_balance.available} USDT",
            f"  - Equity: {input_data.account_balance.equity} USDT",
            "",
            "Current Position:",
        ]

        if input_data.current_position.is_empty:
            lines.append("  - No open position")
        else:
            lines.extend([
                f"  - Direction: {input_data.current_position.direction.value}",
                f"  - Size: {input_data.current_position.size}",
                f"  - Entry Price: {input_data.current_position.entry_price}",
                f"  - Unrealized PnL: {input_data.current_position.unrealized_pnl}",
            ])

        if input_data.analysis_history:
            lines.extend([
                "",
                "Analysis History:",
            ])
            for i, history in enumerate(input_data.analysis_history, 1):
                lines.append(f"  {i}. {history}")

        lines.extend([
            "",
            "Configuration:",
            f"  - Stop Loss Ratio: {input_data.trade_pair_config.get('stop_loss_ratio', 0.02)}",
            f"  - Take Profit Ratio: {input_data.trade_pair_config.get('take_profit_ratio', 0.05)}",
            "",
            "Please analyze the chart and provide your trading decision.",
        ])

        return "\n".join(lines)

    def _parse_analyst_response(self, response: str) -> AnalystOutput:
        """解析分析师响应"""
        # 简单解析，实际可能需要更复杂的逻辑
        return AnalystOutput(
            analysis=response,
            direction="neutral",
        )

    async def call_trader(self, input_data: TraderInput) -> TraderOutput:
        """
        调用交易员Agent

        Args:
            input_data: 交易员输入数据

        Returns:
            交易员输出（交易指令列表）
        """
        system_prompt = self.prompts.get("trader", "")

        # 构建用户消息
        user_message = self._build_trader_message(input_data)

        self.logger.info(f"调用交易员 {input_data.current_position.inst_id}")

        # 重试机制
        for attempt in range(self.MAX_TRADER_RETRIES):
            try:
                response = await self.llm_client.chat_text_only(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    temperature=0.0,
                )

                self.logger.debug(f"交易员响应: {response}")

                # 解析并验证JSON
                instructions = self._parse_trader_response(response)
                return TraderOutput(instructions=instructions)

            except Exception as e:
                self.logger.error(f"交易员响应解析失败 (尝试 {attempt + 1}): {e}")
                if attempt < self.MAX_TRADER_RETRIES - 1:
                    await asyncio.sleep(1)
                else:
                    self.logger.error("达到最大重试次数, 返回空指令")
                    return TraderOutput(instructions=[])

        return TraderOutput(instructions=[])

    def _build_trader_message(self, input_data: TraderInput) -> str:
        """构建交易员用户消息"""
        config = input_data.trade_pair_config

        lines = [
            f"Trading Pair: {input_data.current_position.inst_id}",
            f"Current Price: {input_data.current_price}",
            f"Account Balance: {input_data.account_balance.available} USDT",
            f"Risk Per Trade: {input_data.risk_per_trade * 100}%",
            "",
            "Current Position:",
        ]

        if input_data.current_position.is_empty:
            lines.append("  - No open position")
        else:
            lines.extend([
                f"  - Direction: {input_data.current_position.direction.value}",
                f"  - Size: {input_data.current_position.size}",
                f"  - Entry Price: {input_data.current_position.entry_price}",
            ])

        lines.extend([
            "",
            "Analyst Analysis:",
            input_data.analyst_output.analysis,
            "",
            "Configuration:",
            f"  - Position Size: {config.get('position_size', 0)} USDT",
            f"  - Stop Loss Ratio: {config.get('stop_loss_ratio', 0.02)}",
            f"  - Take Profit Ratio: {config.get('take_profit_ratio', 0.05)}",
            f"  - Leverage: {config.get('leverage', 1)}x",
            "",
            "Please provide trading instructions in JSON format.",
        ])

        return "\n".join(lines)

    def _parse_trader_response(self, response: str) -> list[TradeInstruction]:
        """解析交易员响应为交易指令列表"""
        # 尝试提取JSON部分
        json_str = response

        # 如果响应包含代码块，提取其中的JSON
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0].strip()

        data = json.loads(json_str)

        # 支持单个指令或指令数组
        if isinstance(data, list):
            return [TradeInstruction.from_dict(item) for item in data]
        else:
            return [TradeInstruction.from_dict(data)]

    async def call_compressor(self, input_data: CompressorInput) -> CompressorOutput:
        """
        调用压缩者Agent

        Args:
            input_data: 压缩者输入数据

        Returns:
            压缩后的文本
        """
        system_prompt = self.prompts.get("compressor", "")

        user_message = f"Please compress the following analysis:\n\n{input_data.analyst_output.analysis}"

        self.logger.info("调用压缩者")

        response = await self.llm_client.chat_text_only(
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=0.1,
        )

        self.logger.debug(f"压缩者响应: {response}")

        # 截断到100字
        compressed = response[:100] if len(response) > 100 else response

        return CompressorOutput(compressed_text=compressed)

    async def analyze_and_trade(
        self,
        analyst_input: AnalystInput,
        trader_input: TraderInput,
    ) -> tuple[AnalystOutput, TraderOutput, CompressorOutput]:
        """
        并行调用分析师、交易员和压缩者

        Returns:
            (分析师输出, 交易员输出, 压缩者输出)
        """
        # 先调用分析师
        analyst_output = await self.call_analyst(analyst_input)

        # 更新交易员输入
        trader_input.analyst_output = analyst_output

        # 并行调用交易员和压缩者
        trader_task = self.call_trader(trader_input)
        compressor_task = self.call_compressor(CompressorInput(analyst_output=analyst_output))

        trader_output, compressor_output = await asyncio.gather(
            trader_task, compressor_task
        )

        return analyst_output, trader_output, compressor_output
