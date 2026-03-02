"""Agent调度服务单元测试"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest import IsolatedAsyncioTestCase, mock
from uuid import UUID

from src.domain.agent import CompressorOutput, TraderOutput
from src.domain.config import PromptConfig, TradePairConfig
from src.domain.trading import Position, PositionDirection, TradeInstruction, TradeOperation
from src.services.agent_service import AgentService, TraderJSONError


class MockLLMClient:
    """模拟LLM客户端"""

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = responses or []
        self.call_count = 0
        self.chat_calls: list[dict] = []

    async def chat(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        image_data: bytes | None = None,
        temperature: float = 0.0,
    ) -> str:
        self.chat_calls.append({
            "model": model,
            "system_prompt": system_prompt,
            "user_message": user_message,
            "image_data": image_data is not None,
            "temperature": temperature,
        })

        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return response

        return "默认响应"


class TestAgentService(IsolatedAsyncioTestCase):
    """Agent调度服务测试类"""

    def setUp(self) -> None:
        """设置测试数据"""
        self.prompt_config = PromptConfig(
            analyst="""你是分析师。
当前交易对：{inst_id}，周期：{timeframe}，仓位：{position}，余额：{balance}
历史分析记录：{history}""",
            trader="""你是交易员。
当前交易对：{inst_id}，仓位：{position}，余额：{balance}，开仓金额：{position_size}""",
            compressor="将分析压缩为不超过100字。",
        )
        self.llm_model = "gpt-4o"
        self.max_retries = 3

    def _create_service(self, llm_client: MockLLMClient) -> AgentService:
        """创建Agent服务实例"""
        return AgentService(
            llm_client=llm_client,
            prompt_config=self.prompt_config,
            llm_model=self.llm_model,
            max_trader_retries=self.max_retries,
        )

    async def test_call_analyst(self) -> None:
        """测试分析师Agent调用"""
        mock_llm = MockLLMClient(["分析结果：建议开多仓"])
        service = self._create_service(mock_llm)

        position = Position(inst_id="BTC-USDT-SWAP")

        result = await service.call_analyst(
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
            kline_image_base64="aGVsbG8=",
            analysis_history=["历史分析1", "历史分析2"],
            current_position=position,
            account_balance=Decimal("10000"),
        )

        self.assertEqual(result.analysis, "分析结果：建议开多仓")
        self.assertEqual(mock_llm.call_count, 1)
        self.assertTrue(mock_llm.chat_calls[0]["image_data"])
        self.assertEqual(mock_llm.chat_calls[0]["temperature"], 0.0)

    async def test_call_analyst_empty_history(self) -> None:
        """测试分析师调用（空历史记录）"""
        mock_llm = MockLLMClient(["分析结果"])
        service = self._create_service(mock_llm)

        position = Position(inst_id="BTC-USDT-SWAP")

        await service.call_analyst(
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
            kline_image_base64="aGVsbG8=",
            analysis_history=[],
            current_position=position,
            account_balance=Decimal("10000"),
        )

        self.assertIn("无", mock_llm.chat_calls[0]["system_prompt"])

    async def test_call_trader_success(self) -> None:
        """测试交易员Agent调用成功"""
        json_response = json.dumps([
            {"op": "entry_long", "args": {"size": 100, "stop_loss": 0.02, "take_profit": 0.05}}
        ])
        mock_llm = MockLLMClient([json_response])
        service = self._create_service(mock_llm)

        position = Position(inst_id="BTC-USDT-SWAP")

        result = await service.call_trader(
            analyst_output="建议开多仓",
            current_position=position,
            account_balance=Decimal("10000"),
            position_size_limit=Decimal("100"),
            inst_id="BTC-USDT-SWAP",
        )

        self.assertEqual(len(result.instructions), 1)
        self.assertEqual(result.instructions[0].op, TradeOperation.ENTRY_LONG)
        self.assertEqual(result.instructions[0].args["size"], 100)

    async def test_call_trader_with_markdown(self) -> None:
        """测试交易员调用（带markdown标记）"""
        json_response = "```json\n" + json.dumps([
            {"op": "close_position"}
        ]) + "\n```"
        mock_llm = MockLLMClient([json_response])
        service = self._create_service(mock_llm)

        position = Position(
            inst_id="BTC-USDT-SWAP",
            direction=PositionDirection.LONG,
            size=Decimal("1"),
        )

        result = await service.call_trader(
            analyst_output="建议平仓",
            current_position=position,
            account_balance=Decimal("10000"),
            position_size_limit=Decimal("100"),
            inst_id="BTC-USDT-SWAP",
        )

        self.assertEqual(len(result.instructions), 1)
        self.assertEqual(result.instructions[0].op, TradeOperation.CLOSE_POSITION)

    async def test_call_trader_retry_success(self) -> None:
        """测试交易员调用重试成功"""
        mock_llm = MockLLMClient([
            "无效JSON",
            json.dumps([{"op": "entry_long", "args": {"size": 100, "stop_loss": 0.02, "take_profit": 0.05}}]),
        ])
        service = self._create_service(mock_llm)

        position = Position(inst_id="BTC-USDT-SWAP")

        result = await service.call_trader(
            analyst_output="建议开多",
            current_position=position,
            account_balance=Decimal("10000"),
            position_size_limit=Decimal("100"),
            inst_id="BTC-USDT-SWAP",
        )

        self.assertEqual(len(result.instructions), 1)
        self.assertEqual(mock_llm.call_count, 2)

    async def test_call_trader_retry_exhausted(self) -> None:
        """测试交易员调用重试次数耗尽"""
        mock_llm = MockLLMClient([
            "无效JSON1",
            "无效JSON2",
            "无效JSON3",
        ])
        service = self._create_service(mock_llm)

        position = Position(inst_id="BTC-USDT-SWAP")

        with self.assertRaises(TraderJSONError):
            await service.call_trader(
                analyst_output="建议开多",
                current_position=position,
                account_balance=Decimal("10000"),
                position_size_limit=Decimal("100"),
                inst_id="BTC-USDT-SWAP",
            )

        self.assertEqual(mock_llm.call_count, 3)

    async def test_call_trader_invalid_op(self) -> None:
        """测试交易员调用无效操作类型"""
        mock_llm = MockLLMClient([
            json.dumps([{"op": "invalid_op"}]),
        ])
        service = self._create_service(mock_llm)

        position = Position(inst_id="BTC-USDT-SWAP")

        with self.assertRaises(TraderJSONError):
            await service.call_trader(
                analyst_output="建议操作",
                current_position=position,
                account_balance=Decimal("10000"),
                position_size_limit=Decimal("100"),
                inst_id="BTC-USDT-SWAP",
            )

    async def test_call_compressor(self) -> None:
        """测试压缩者Agent调用"""
        mock_llm = MockLLMClient(["建议开多，止损2%，止盈5%，依据EMA金叉"])
        service = self._create_service(mock_llm)

        result = await service.call_compressor(analyst_output="详细分析内容...")

        self.assertEqual(result.compressed_text, "建议开多，止损2%，止盈5%，依据EMA金叉")
        self.assertEqual(mock_llm.chat_calls[0]["temperature"], 0.1)

    async def test_call_compressor_truncate(self) -> None:
        """测试压缩者调用（超长文本截断）"""
        long_text = "A" * 150
        mock_llm = MockLLMClient([long_text])
        service = self._create_service(mock_llm)

        result = await service.call_compressor(analyst_output="分析")

        self.assertEqual(len(result.compressed_text), 100)
        self.assertTrue(result.compressed_text.endswith("..."))

    async def test_analyze_and_trade(self) -> None:
        """测试完整分析流程"""
        mock_llm = MockLLMClient([
            "建议开多仓，止损2%",  # 分析师
            json.dumps([{"op": "entry_long", "args": {"size": 100, "stop_loss": 0.02, "take_profit": 0.05}}]),  # 交易员
            "开多，止损2%，EMA金叉",  # 压缩者
        ])
        service = self._create_service(mock_llm)

        position = Position(inst_id="BTC-USDT-SWAP")

        instructions, compressed = await service.analyze_and_trade(
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
            kline_image_base64="aGVsbG8=",
            analysis_history=[],
            current_position=position,
            account_balance=Decimal("10000"),
            position_size_limit=Decimal("100"),
        )

        self.assertEqual(len(instructions), 1)
        self.assertEqual(instructions[0].op, TradeOperation.ENTRY_LONG)
        self.assertEqual(compressed, "开多，止损2%，EMA金叉")
        self.assertEqual(mock_llm.call_count, 3)

    async def test_analyze_and_trade_compressor_fail(self) -> None:
        """测试完整流程（压缩者失败）"""

        class FailingCompressorLLM:
            async def chat(self, **kwargs):
                if "压缩" in kwargs.get("system_prompt", ""):
                    raise Exception("压缩失败")
                if kwargs.get("image_data"):
                    return "建议开多"
                return json.dumps([{"op": "entry_long", "args": {"size": 100, "stop_loss": 0.02, "take_profit": 0.05}}])

        service = self._create_service(FailingCompressorLLM())

        position = Position(inst_id="BTC-USDT-SWAP")

        instructions, compressed = await service.analyze_and_trade(
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
            kline_image_base64="aGVsbG8=",
            analysis_history=[],
            current_position=position,
            account_balance=Decimal("10000"),
            position_size_limit=Decimal("100"),
        )

        self.assertEqual(len(instructions), 1)
        self.assertTrue(len(compressed) <= 100)

    async def test_format_position_empty(self) -> None:
        """测试格式化空仓"""
        mock_llm = MockLLMClient(["响应"])
        service = self._create_service(mock_llm)

        position = Position(inst_id="BTC-USDT-SWAP")
        result = service._format_position(position)

        self.assertEqual(result, "空仓")

    async def test_format_position_long(self) -> None:
        """测试格式化多仓"""
        mock_llm = MockLLMClient(["响应"])
        service = self._create_service(mock_llm)

        position = Position(
            inst_id="BTC-USDT-SWAP",
            direction=PositionDirection.LONG,
            size=Decimal("1.5"),
            entry_price=Decimal("50000"),
        )
        result = service._format_position(position)

        self.assertIn("long", result.lower())
        self.assertIn("1.5", result)
        self.assertIn("50000", result)

    async def test_parse_trader_response_multiple(self) -> None:
        """测试解析多条指令"""
        mock_llm = MockLLMClient([])
        service = self._create_service(mock_llm)

        response = json.dumps([
            {"op": "change_stop", "args": {"stop_price": 48000}, "client_oid": "test-uuid-1"},
            {"op": "change_profit", "args": {"profit_price": 55000}},
        ])

        instructions = service._parse_trader_response(response)

        self.assertEqual(len(instructions), 2)
        self.assertEqual(instructions[0].op, TradeOperation.CHANGE_STOP)
        self.assertEqual(instructions[0].client_oid, "test-uuid-1")
        self.assertEqual(instructions[1].op, TradeOperation.CHANGE_PROFIT)
        self.assertTrue(UUID(instructions[1].client_oid))

    async def test_parse_trader_response_empty_array(self) -> None:
        """测试解析空指令数组"""
        mock_llm = MockLLMClient([])
        service = self._create_service(mock_llm)

        response = json.dumps([])
        instructions = service._parse_trader_response(response)

        self.assertEqual(len(instructions), 0)

    async def test_prompt_placeholder_replacement(self) -> None:
        """测试Prompt占位符替换"""
        mock_llm = MockLLMClient(["分析结果"])
        service = self._create_service(mock_llm)

        position = Position(
            inst_id="BTC-USDT-SWAP",
            direction=PositionDirection.SHORT,
            size=Decimal("0.5"),
            entry_price=Decimal("3000"),
        )

        await service.call_analyst(
            inst_id="ETH-USDT-SWAP",
            timeframe="4H",
            kline_image_base64="aGVsbG8=",
            analysis_history=["历史1"],
            current_position=position,
            account_balance=Decimal("5000"),
        )

        system_prompt = mock_llm.chat_calls[0]["system_prompt"]
        self.assertIn("ETH-USDT-SWAP", system_prompt)
        self.assertIn("4H", system_prompt)
        self.assertIn("short", system_prompt.lower())
        self.assertIn("5000", system_prompt)
        self.assertIn("历史1", system_prompt)
