"""Agent调度服务

实现三个Agent的异步调度和结果处理。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.domain.agent import (
    AnalystInput,
    AnalystOutput,
    CompressorInput,
    CompressorOutput,
    TraderInput,
    TraderOutput,
)
from src.domain.config import PromptConfig, TradePairConfig
from src.domain.trading import Position, TradeInstruction
from src.infrastructure.logger import Logger

if TYPE_CHECKING:
    from src.infrastructure.llm_client import LLMClient


class AgentService:
    """Agent调度服务

    负责异步调用分析师、交易员、压缩者三个Agent，
    处理Prompt占位符替换和JSON格式校验重试。
    """

    def __init__(
        self,
        llm_client: LLMClient,
        prompt_config: PromptConfig,
        llm_model: str,
        max_trader_retries: int = 3,
    ) -> None:
        """初始化Agent调度服务

        Args:
            llm_client: LLM客户端
            prompt_config: Prompt配置
            llm_model: LLM模型名称
            max_trader_retries: 交易员JSON格式错误最大重试次数
        """
        self._llm_client = llm_client
        self._prompt_config = prompt_config
        self._llm_model = llm_model
        self._max_trader_retries = max_trader_retries
        self._logger = Logger()

    async def call_analyst(
        self,
        inst_id: str,
        timeframe: str,
        kline_image_base64: str,
        analysis_history: list[str],
        current_position: Position,
        account_balance: Decimal,
    ) -> AnalystOutput:
        """调用分析师Agent

        Args:
            inst_id: 交易对ID
            timeframe: K线周期
            kline_image_base64: K线图base64编码
            analysis_history: 历史分析记录
            current_position: 当前仓位
            account_balance: 账户余额

        Returns:
            分析师输出
        """
        history_text = self._format_history(analysis_history)
        position_text = self._format_position(current_position)

        system_prompt = self._prompt_config.format_analyst_prompt(
            inst_id=inst_id,
            timeframe=timeframe,
            position=position_text,
            balance=account_balance,
            history=history_text,
        )

        user_message = "请基于K线图进行技术分析，给出交易决策建议。"

        image_data = self._base64_to_bytes(kline_image_base64)

        self._logger.info(f"调用分析师Agent: {inst_id}")

        response = await self._llm_client.chat(
            model=self._llm_model,
            system_prompt=system_prompt,
            user_message=user_message,
            image_data=image_data,
            temperature=0.0,
        )

        self._logger.info(f"分析师Agent响应: {inst_id}")

        return AnalystOutput(
            analysis=response,
            trading_decision=self._extract_trading_decision(response),
        )

    async def call_trader(
        self,
        analyst_output: str,
        current_position: Position,
        account_balance: Decimal,
        position_size_limit: Decimal,
        inst_id: str,
    ) -> TraderOutput:
        """调用交易员Agent

        对交易员输出进行JSON Schema校验，失败时重试。

        Args:
            analyst_output: 分析师输出
            current_position: 当前仓位
            account_balance: 账户余额
            position_size_limit: 开仓金额限制
            inst_id: 交易对ID

        Returns:
            交易员输出

        Raises:
            TraderJSONError: JSON格式错误且重试后仍失败
        """
        position_text = self._format_position(current_position)

        system_prompt = self._prompt_config.format_trader_prompt(
            inst_id=inst_id,
            position=position_text,
            balance=account_balance,
            position_size=position_size_limit,
        )

        last_error: Exception | None = None

        for attempt in range(self._max_trader_retries):
            try:
                user_message = f"分析师输出：\n{analyst_output}\n\n请生成JSON交易指令数组。"

                self._logger.info(
                    f"调用交易员Agent: {inst_id}, 尝试 {attempt + 1}/{self._max_trader_retries}"
                )

                response = await self._llm_client.chat(
                    model=self._llm_model,
                    system_prompt=system_prompt,
                    user_message=user_message,
                    temperature=0.0,
                )

                instructions = self._parse_trader_response(response)

                self._logger.info(
                    f"交易员Agent响应成功: {inst_id}, 指令数={len(instructions)}"
                )

                return TraderOutput(instructions=instructions)

            except (json.JSONDecodeError, ValueError, KeyError) as e:
                last_error = e
                error_msg = f"交易员输出JSON解析失败: {e}"
                self._logger.warning(
                    f"{error_msg}, 尝试重试 ({attempt + 1}/{self._max_trader_retries})"
                )

                if attempt < self._max_trader_retries - 1:
                    error_feedback = (
                        f"JSON解析错误: {e}\n"
                        f"请严格按照JSON数组格式输出，不要包含任何markdown标记或解释文字。"
                    )
                    analyst_output = f"{analyst_output}\n\n[错误反馈]\n{error_feedback}"
                    await asyncio.sleep(1)

        error_msg = f"交易员Agent JSON格式错误，已重试{self._max_trader_retries}次: {last_error}"
        self._logger.error(error_msg)
        raise TraderJSONError(error_msg) from last_error

    async def call_compressor(self, analyst_output: str) -> CompressorOutput:
        """调用压缩者Agent

        Args:
            analyst_output: 分析师输出

        Returns:
            压缩后的分析结果
        """
        system_prompt = self._prompt_config.compressor_system_prompt
        user_message = analyst_output

        self._logger.info("调用压缩者Agent")

        response = await self._llm_client.chat(
            model=self._llm_model,
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=0.1,
        )

        compressed_text = response.strip()
        if len(compressed_text) > 100:
            compressed_text = compressed_text[:97] + "..."

        self._logger.info(f"压缩者Agent响应: {compressed_text[:50]}...")

        return CompressorOutput(compressed_text=compressed_text)

    async def analyze_and_trade(
        self,
        inst_id: str,
        timeframe: str,
        kline_image_base64: str,
        analysis_history: list[str],
        current_position: Position,
        account_balance: Decimal,
        position_size_limit: Decimal,
    ) -> tuple[list[TradeInstruction], str]:
        """执行完整分析流程

        1. 调用分析师Agent
        2. 并行调用交易员和压缩者Agent
        3. 返回交易指令和压缩后的分析

        Args:
            inst_id: 交易对ID
            timeframe: K线周期
            kline_image_base64: K线图base64编码
            analysis_history: 历史分析记录
            current_position: 当前仓位
            account_balance: 账户余额
            position_size_limit: 开仓金额限制

        Returns:
            (交易指令列表, 压缩后的分析文本)

        Raises:
            TraderJSONError: 交易员输出JSON格式错误且重试失败
        """
        analyst_output = await self.call_analyst(
            inst_id=inst_id,
            timeframe=timeframe,
            kline_image_base64=kline_image_base64,
            analysis_history=analysis_history,
            current_position=current_position,
            account_balance=account_balance,
        )

        trader_task = self.call_trader(
            analyst_output=analyst_output.analysis,
            current_position=current_position,
            account_balance=account_balance,
            position_size_limit=position_size_limit,
            inst_id=inst_id,
        )

        compressor_task = self.call_compressor(analyst_output=analyst_output.analysis)

        trader_result, compressor_result = await asyncio.gather(
            trader_task, compressor_task, return_exceptions=True
        )

        if isinstance(trader_result, Exception):
            raise trader_result

        if isinstance(compressor_result, Exception):
            self._logger.warning(f"压缩者Agent调用失败: {compressor_result}")
            compressed_text = analyst_output.analysis[:100]
        else:
            compressed_text = compressor_result.compressed_text

        return trader_result.instructions, compressed_text

    def _format_history(self, history: list[str]) -> str:
        """格式化历史记录

        Args:
            history: 历史分析记录列表

        Returns:
            格式化的历史记录文本
        """
        if not history:
            return "无"

        lines = []
        for i, record in enumerate(history, 1):
            lines.append(f"{i}. {record}")
        return "\n".join(lines)

    def _format_position(self, position: Position) -> str:
        """格式化仓位信息

        Args:
            position: 仓位对象

        Returns:
            格式化的仓位文本
        """
        if position.is_empty():
            return "空仓"
        return f"{position.direction.value} 数量={position.size} 均价={position.entry_price}"

    def _base64_to_bytes(self, base64_string: str) -> bytes:
        """将base64字符串转换为bytes

        Args:
            base64_string: base64编码字符串

        Returns:
            解码后的bytes
        """
        import base64

        return base64.b64decode(base64_string)

    def _extract_trading_decision(self, analysis: str) -> str:
        """从分析文本中提取交易决策

        Args:
            analysis: 分析文本

        Returns:
            交易决策摘要
        """
        lines = analysis.split("\n")
        for line in lines:
            line_lower = line.lower()
            if any(
                keyword in line_lower
                for keyword in ["建议", "决策", "方向", "操作", "买入", "卖出", "开仓", "平仓"]
            ):
                return line.strip()
        return analysis[:100]

    def _parse_trader_response(self, response: str) -> list[TradeInstruction]:
        """解析交易员响应

        Args:
            response: 交易员响应文本

        Returns:
            交易指令列表

        Raises:
            json.JSONDecodeError: JSON解析失败
            ValueError: 数据格式错误
        """
        cleaned_response = response.strip()

        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        elif cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]

        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]

        cleaned_response = cleaned_response.strip()

        data = json.loads(cleaned_response)

        if not isinstance(data, list):
            raise ValueError("交易员输出必须是JSON数组")

        instructions = []
        for item in data:
            if not isinstance(item, dict):
                raise ValueError(f"指令项必须是对象: {item}")

            op_str = item.get("op")
            if op_str is None:
                raise ValueError(f"指令缺少 op 字段: {item}")

            from src.domain.trading import TradeOperation

            try:
                op = TradeOperation(op_str)
            except ValueError as e:
                raise ValueError(f"无效的操作类型: {op_str}") from e

            instruction = TradeInstruction(
                op=op,
                args=item.get("args", {}),
                client_oid=item.get("client_oid") or self._generate_client_oid(),
            )
            instructions.append(instruction)

        return instructions

    def _generate_client_oid(self) -> str:
        """生成客户端订单ID

        Returns:
            UUID格式的客户端订单ID
        """
        from uuid import uuid4

        return str(uuid4())


class TraderJSONError(Exception):
    """交易员JSON格式错误"""

    pass
