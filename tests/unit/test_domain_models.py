"""领域模型单元测试

测试所有领域模型的序列化/反序列化、验证逻辑和边界条件。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

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


class TestKline:
    """K线模型测试"""

    def test_valid_kline_creation(self):
        """测试创建有效的K线对象"""
        kline = Kline(
            timestamp=1704067200000,
            open=Decimal("42000.00"),
            high=Decimal("43000.00"),
            low=Decimal("41000.00"),
            close=Decimal("42500.00"),
            vol=Decimal("100.5"),
            confirm=1,
        )
        assert kline.timestamp == 1704067200000
        assert kline.open == Decimal("42000.00")
        assert kline.confirm == 1

    def test_kline_from_okx_data(self):
        """测试从OKX数据创建K线"""
        okx_data = [1704067200000, "42000.00", "43000.00", "41000.00", "42500.00", "100.5", 1]
        kline = Kline.from_okx_data(okx_data)
        assert kline.timestamp == 1704067200000
        assert kline.open == Decimal("42000.00")
        assert kline.high == Decimal("43000.00")
        assert kline.low == Decimal("41000.00")
        assert kline.close == Decimal("42500.00")
        assert kline.vol == Decimal("100.5")
        assert kline.confirm == 1

    def test_kline_serialization(self):
        """测试K线序列化为字典"""
        kline = Kline(
            timestamp=1704067200000,
            open=Decimal("42000.00"),
            high=Decimal("43000.00"),
            low=Decimal("41000.00"),
            close=Decimal("42500.00"),
            vol=Decimal("100.5"),
            confirm=1,
        )
        data = kline.to_dict()
        assert data["timestamp"] == 1704067200000
        assert data["open"] == "42000.00"
        assert data["high"] == "43000.00"

    def test_invalid_high_low(self):
        """测试最高价小于最低价时抛出错误"""
        with pytest.raises(ValidationError):
            Kline(
                timestamp=1704067200000,
                open=Decimal("42000.00"),
                high=Decimal("40000.00"),  # 错误：high < low
                low=Decimal("41000.00"),
                close=Decimal("42500.00"),
                vol=Decimal("100.5"),
            )

    def test_negative_price(self):
        """测试负价格抛出错误"""
        with pytest.raises(ValidationError):
            Kline(
                timestamp=1704067200000,
                open=Decimal("-100"),
                high=Decimal("43000.00"),
                low=Decimal("41000.00"),
                close=Decimal("42500.00"),
                vol=Decimal("100.5"),
            )


class TestPosition:
    """仓位模型测试"""

    def test_empty_position(self):
        """测试空仓创建"""
        position = Position(inst_id="BTC-USDT-SWAP")
        assert position.is_empty()
        assert position.direction == PositionDirection.EMPTY
        assert position.size == 0

    def test_long_position(self):
        """测试多仓创建"""
        position = Position(
            inst_id="BTC-USDT-SWAP",
            direction=PositionDirection.LONG,
            size=Decimal("1.5"),
            entry_price=Decimal("42000.00"),
            stop_price=Decimal("40000.00"),
            profit_price=Decimal("45000.00"),
            unrealized_pnl=Decimal("500"),
        )
        assert not position.is_empty()
        assert position.direction == PositionDirection.LONG
        assert position.to_display_string() == "long 1.5 @ 42000.00"

    def test_invalid_empty_position_with_size(self):
        """测试空仓但有持仓数量时抛出错误"""
        with pytest.raises(ValidationError):
            Position(
                inst_id="BTC-USDT-SWAP",
                direction=PositionDirection.EMPTY,
                size=Decimal("1.0"),  # 错误：空仓但有持仓
            )

    def test_invalid_position_without_size(self):
        """测试持仓方向非空但数量为0时抛出错误"""
        with pytest.raises(ValidationError):
            Position(
                inst_id="BTC-USDT-SWAP",
                direction=PositionDirection.LONG,
                size=Decimal("0"),  # 错误：多仓但持仓为0
            )

    def test_negative_size(self):
        """测试负持仓数量抛出错误"""
        with pytest.raises(ValidationError):
            Position(
                inst_id="BTC-USDT-SWAP",
                direction=PositionDirection.LONG,
                size=Decimal("-1.0"),
            )


class TestTradeInstruction:
    """交易指令模型测试"""

    def test_entry_long_instruction(self):
        """测试开多仓指令"""
        instruction = TradeInstruction(
            op=TradeOperation.ENTRY_LONG,
            args={"size": Decimal("100"), "stop_loss": Decimal("40000"), "take_profit": Decimal("45000")},
        )
        assert instruction.op == TradeOperation.ENTRY_LONG
        assert "client_oid" in instruction.model_dump()

    def test_entry_instruction_missing_stop_loss(self):
        """测试开仓指令缺少止损参数时抛出错误"""
        with pytest.raises(ValidationError) as exc_info:
            TradeInstruction(
                op=TradeOperation.ENTRY_LONG,
                args={"size": Decimal("100"), "take_profit": Decimal("45000")},  # 缺少 stop_loss
            )
        assert "stop_loss" in str(exc_info.value)

    def test_entry_instruction_missing_take_profit(self):
        """测试开仓指令缺少止盈参数时抛出错误"""
        with pytest.raises(ValidationError) as exc_info:
            TradeInstruction(
                op=TradeOperation.ENTRY_SHORT,
                args={"size": Decimal("100"), "stop_loss": Decimal("40000")},  # 缺少 take_profit
            )
        assert "take_profit" in str(exc_info.value)

    def test_close_position_instruction(self):
        """测试平仓指令（不需要额外参数）"""
        instruction = TradeInstruction(op=TradeOperation.CLOSE_POSITION)
        assert instruction.op == TradeOperation.CLOSE_POSITION
        assert instruction.args == {}

    def test_change_stop_instruction(self):
        """测试修改止损指令"""
        instruction = TradeInstruction(
            op=TradeOperation.CHANGE_STOP,
            args={"stop_price": Decimal("39000")},
        )
        assert instruction.op == TradeOperation.CHANGE_STOP

    def test_change_stop_missing_price(self):
        """测试修改止损指令缺少价格时抛出错误"""
        with pytest.raises(ValidationError) as exc_info:
            TradeInstruction(
                op=TradeOperation.CHANGE_STOP,
                args={},  # 缺少 stop_price
            )
        assert "stop_price" in str(exc_info.value)

    def test_exit_instruction(self):
        """测试减仓指令"""
        instruction = TradeInstruction(
            op=TradeOperation.EXIT_LONG,
            args={"size": Decimal("0.5")},
        )
        assert instruction.op == TradeOperation.EXIT_LONG

    def test_validate_against_position_entry_with_existing_position(self):
        """测试开仓时已有反向仓位抛出错误"""
        instruction = TradeInstruction(
            op=TradeOperation.ENTRY_LONG,
            args={"size": Decimal("100"), "stop_loss": Decimal("40000"), "take_profit": Decimal("45000")},
        )
        position = Position(
            inst_id="BTC-USDT-SWAP",
            direction=PositionDirection.SHORT,
            size=Decimal("1.0"),
            entry_price=Decimal("42000"),
        )
        with pytest.raises(ValueError) as exc_info:
            instruction.validate_against_position(position)
        assert "已有short仓位" in str(exc_info.value)

    def test_validate_exit_size_too_large(self):
        """测试减仓数量大于等于持仓时抛出错误"""
        instruction = TradeInstruction(
            op=TradeOperation.EXIT_LONG,
            args={"size": Decimal("2.0")},  # 大于持仓
        )
        position = Position(
            inst_id="BTC-USDT-SWAP",
            direction=PositionDirection.LONG,
            size=Decimal("1.5"),
            entry_price=Decimal("42000"),
        )
        with pytest.raises(ValueError) as exc_info:
            instruction.validate_against_position(position)
        assert "必须小于当前持仓" in str(exc_info.value)

    def test_validate_exit_on_empty_position(self):
        """测试空仓时减仓抛出错误"""
        instruction = TradeInstruction(
            op=TradeOperation.EXIT_LONG,
            args={"size": Decimal("0.5")},
        )
        position = Position(inst_id="BTC-USDT-SWAP")
        with pytest.raises(ValueError) as exc_info:
            instruction.validate_against_position(position)
        assert "空仓无法执行" in str(exc_info.value)

    def test_validate_position_size_limit(self):
        """测试开仓金额超过限制抛出错误"""
        instruction = TradeInstruction(
            op=TradeOperation.ENTRY_LONG,
            args={"size": Decimal("200"), "stop_loss": Decimal("40000"), "take_profit": Decimal("45000")},
        )
        position = Position(inst_id="BTC-USDT-SWAP")
        with pytest.raises(ValueError) as exc_info:
            instruction.validate_against_position(position, Decimal("100"))
        assert "超过限制" in str(exc_info.value)


class TestTradeRecord:
    """交易记录模型测试"""

    def test_trade_record_creation(self):
        """测试交易记录创建"""
        record = TradeRecord(
            timestamp=1704067200000,
            inst_id="BTC-USDT-SWAP",
            position_direction=PositionDirection.LONG,
            position_size=Decimal("1.5"),
            entry_avg_price=Decimal("42000.00"),
            exit_avg_price=Decimal("43000.00"),
            realized_pnl=Decimal("1500"),
            balance_after_close=Decimal("10000"),
            order_id="123456789",
        )
        assert record.inst_id == "BTC-USDT-SWAP"
        assert record.realized_pnl == Decimal("1500")

    def test_trade_record_to_csv_row(self):
        """测试交易记录转换为CSV行"""
        record = TradeRecord(
            timestamp=1704067200000,
            inst_id="BTC-USDT-SWAP",
            position_direction=PositionDirection.LONG,
            position_size=Decimal("1.5"),
            entry_avg_price=Decimal("42000.00"),
            exit_avg_price=Decimal("43000.00"),
            realized_pnl=Decimal("1500"),
            balance_after_close=Decimal("10000"),
            order_id="123456789",
        )
        row = record.to_csv_row()
        assert row["inst_id"] == "BTC-USDT-SWAP"
        assert row["position_direction"] == "long"
        assert row["realized_pnl"] == "1500"
        assert "datetime" in row

    def test_csv_headers(self):
        """测试CSV表头"""
        headers = TradeRecord.get_csv_headers()
        assert "timestamp" in headers
        assert "inst_id" in headers
        assert "realized_pnl" in headers
        assert "order_id" in headers


class TestAgentModels:
    """Agent模型测试"""

    def test_analyst_input_creation(self):
        """测试分析师输入创建"""
        position = Position(inst_id="BTC-USDT-SWAP")
        input_data = AnalystInput(
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
            kline_image_base64="base64encodedstring",
            analysis_history=["历史分析1", "历史分析2"],
            current_position=position,
            account_balance=Decimal("10000"),
        )
        assert input_data.inst_id == "BTC-USDT-SWAP"
        assert len(input_data.analysis_history) == 2

    def test_analyst_output_creation(self):
        """测试分析师输出创建"""
        output = AnalystOutput(
            analysis="看涨趋势",
            trading_decision="建议开多仓",
        )
        assert output.analysis == "看涨趋势"

    def test_trader_input_creation(self):
        """测试交易员输入创建"""
        position = Position(inst_id="BTC-USDT-SWAP")
        input_data = TraderInput(
            analyst_output="分析师建议开多仓",
            current_position=position,
            account_balance=Decimal("10000"),
            current_price=Decimal("50000"),
            risk_per_trade=Decimal("0.01"),
            inst_id="BTC-USDT-SWAP",
        )
        assert input_data.current_price == Decimal("50000")
        assert input_data.risk_per_trade == Decimal("0.01")

    def test_trader_output_from_json(self):
        """测试从JSON解析交易员输出"""
        json_data = [
            {"op": "entry_long", "args": {"size": 100, "stop_loss": 40000, "take_profit": 45000}},
            {"op": "close_position"},
        ]
        output = TraderOutput.from_json(json_data)
        assert len(output.instructions) == 2
        assert output.instructions[0].op == TradeOperation.ENTRY_LONG
        assert output.instructions[1].op == TradeOperation.CLOSE_POSITION

    def test_trader_output_from_invalid_json_not_array(self):
        """测试从非数组JSON解析时抛出错误"""
        with pytest.raises(ValueError) as exc_info:
            TraderOutput.from_json({"op": "entry_long"})  # 不是数组
        assert "必须是JSON数组" in str(exc_info.value)

    def test_trader_output_from_invalid_json_missing_op(self):
        """测试从缺少op字段的JSON解析时抛出错误"""
        with pytest.raises(ValueError) as exc_info:
            TraderOutput.from_json([{"args": {"size": 100}}])  # 缺少 op
        assert "缺少 op 字段" in str(exc_info.value)

    def test_trader_output_from_invalid_json_invalid_op(self):
        """测试从无效op值的JSON解析时抛出错误"""
        with pytest.raises(ValueError) as exc_info:
            TraderOutput.from_json([{"op": "invalid_op"}])
        assert "无效的操作类型" in str(exc_info.value)

    def test_trader_output_json_schema(self):
        """测试交易员输出JSON Schema"""
        schema = TraderOutput.get_json_schema()
        assert schema["type"] == "array"
        assert "items" in schema
        assert "op" in schema["items"]["properties"]

    def test_compressor_input_creation(self):
        """测试压缩者输入创建"""
        input_data = CompressorInput(analyst_output="分析师输出内容")
        assert input_data.analyst_output == "分析师输出内容"

    def test_compressor_output_creation(self):
        """测试压缩者输出创建"""
        output = CompressorOutput(compressed_text="看涨，止损40000，止盈45000")
        assert output.compressed_text == "看涨，止损40000，止盈45000"

    def test_compressor_output_too_long(self):
        """测试压缩文本超过100字时抛出错误"""
        long_text = "这是一段很长的文本，用来测试超过100字的情况。" * 5  # 超过100字
        with pytest.raises(ValidationError) as exc_info:
            CompressorOutput(compressed_text=long_text)
        assert "不能超过100字" in str(exc_info.value)


class TestEventModels:
    """事件模型测试"""

    def test_kline_close_event(self):
        """测试K线收盘事件"""
        kline = Kline(
            timestamp=1704067200000,
            open=Decimal("42000.00"),
            high=Decimal("43000.00"),
            low=Decimal("41000.00"),
            close=Decimal("42500.00"),
            vol=Decimal("100.5"),
            confirm=1,
        )
        event = KlineCloseEvent(
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
            kline=kline,
        )
        assert event.inst_id == "BTC-USDT-SWAP"
        assert event.kline.close == Decimal("42500.00")

    def test_trade_complete_event(self):
        """测试交易完成事件"""
        result = TradeExecutionResult(success=True, order_id="123456")
        event = TradeCompleteEvent(
            inst_id="BTC-USDT-SWAP",
            op=TradeOperation.ENTRY_LONG,
            order_id="123456",
            execution_result=result,
        )
        assert event.execution_result.success
        assert event.execution_result.order_id == "123456"

    def test_trade_complete_event_failure(self):
        """测试交易失败事件"""
        result = TradeExecutionResult(
            success=False,
            error_message="余额不足",
        )
        event = TradeCompleteEvent(
            inst_id="BTC-USDT-SWAP",
            op=TradeOperation.ENTRY_LONG,
            execution_result=result,
            error_message="余额不足",
        )
        assert not event.execution_result.success
        assert event.error_message == "余额不足"

    def test_position_close_event(self):
        """测试平仓完成事件"""
        position = Position(
            inst_id="BTC-USDT-SWAP",
            direction=PositionDirection.LONG,
            size=Decimal("1.5"),
            entry_price=Decimal("42000.00"),
        )
        record = TradeRecord(
            timestamp=1704067200000,
            inst_id="BTC-USDT-SWAP",
            position_direction=PositionDirection.LONG,
            position_size=Decimal("1.5"),
            entry_avg_price=Decimal("42000.00"),
            exit_avg_price=Decimal("43000.00"),
            realized_pnl=Decimal("1500"),
            balance_after_close=Decimal("10000"),
            order_id="123456789",
        )
        event = PositionCloseEvent(
            inst_id="BTC-USDT-SWAP",
            closed_position=position,
            balance_after_close=Decimal("10000"),
            trade_record=record,
        )
        assert event.inst_id == "BTC-USDT-SWAP"
        assert event.balance_after_close == Decimal("10000")


class TestConfigModels:
    """配置模型测试"""

    def test_trade_pair_config(self):
        """测试交易对配置"""
        config = TradePairConfig(
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
            leverage=10,
            position_size=Decimal("100"),
            stop_loss_ratio=Decimal("0.02"),
            take_profit_ratio=Decimal("0.05"),
        )
        assert config.inst_id == "BTC-USDT-SWAP"
        assert config.leverage == 10
        assert config.position_size == Decimal("100")

    def test_trade_pair_config_invalid_leverage(self):
        """测试无效杠杆倍数抛出错误"""
        with pytest.raises(ValidationError):
            TradePairConfig(
                inst_id="BTC-USDT-SWAP",
                timeframe="1H",
                leverage=200,  # 超过125
                position_size=Decimal("100"),
                stop_loss_ratio=Decimal("0.02"),
                take_profit_ratio=Decimal("0.05"),
            )

    def test_global_config(self):
        """测试全局配置"""
        config = GlobalConfig(
            demo_mode=True,
            log_level="INFO",
            log_dir="./logs",
            max_analysis_history_length=10,
            k_line_count=100,
            llm_model="gpt-4o",
            trade_record_path="./trade_records.csv",
            td_mode="isolated",
        )
        assert config.demo_mode
        assert config.llm_model == "gpt-4o"

    def test_global_config_invalid_td_mode(self):
        """测试无效持仓模式抛出错误"""
        with pytest.raises(ValidationError):
            GlobalConfig(
                llm_model="gpt-4o",
                td_mode="invalid",  # 无效值
            )

    def test_full_config(self):
        """测试完整配置"""
        global_config = GlobalConfig(
            demo_mode=True,
            log_level="INFO",
            llm_model="gpt-4o",
        )
        trade_pairs = [
            TradePairConfig(
                inst_id="BTC-USDT-SWAP",
                timeframe="1H",
                leverage=10,
                position_size=Decimal("100"),
                stop_loss_ratio=Decimal("0.02"),
                take_profit_ratio=Decimal("0.05"),
            ),
        ]
        config = Config(global_config=global_config, trade_pairs=trade_pairs)
        assert len(config.trade_pairs) == 1
        assert config.trade_pairs[0].inst_id == "BTC-USDT-SWAP"

    def test_config_empty_trade_pairs(self):
        """测试空交易对列表抛出错误"""
        global_config = GlobalConfig(llm_model="gpt-4o")
        with pytest.raises(ValidationError):
            Config(global_config=global_config, trade_pairs=[])  # 空列表


class TestPromptConfig:
    """Prompt配置模型测试"""

    def test_prompt_config_creation(self):
        """测试Prompt配置创建"""
        config = PromptConfig(
            analyst="分析师Prompt {inst_id}",
            trader="交易员Prompt {position}",
            compressor="压缩者Prompt",
        )
        assert "分析师Prompt" in config.analyst_system_prompt

    def test_format_analyst_prompt(self):
        """测试格式化分析师Prompt"""
        config = PromptConfig(
            analyst="交易对：{inst_id}，周期：{timeframe}，仓位：{position}，余额：{balance}，历史：{history}",
            trader="交易员",
            compressor="压缩者",
        )
        formatted = config.format_analyst_prompt(
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
            position="long 1.5",
            balance=Decimal("10000"),
            history="历史分析",
        )
        assert "BTC-USDT-SWAP" in formatted
        assert "1H" in formatted
        assert "long 1.5" in formatted

    def test_format_trader_prompt(self):
        """测试格式化交易员Prompt"""
        config = PromptConfig(
            analyst="分析师",
            trader="交易对：{inst_id}，仓位：{position}，余额：{balance}，当前价格：{current_price}，单笔风险百分比：{risk_per_trade}",
            compressor="压缩者",
        )
        formatted = config.format_trader_prompt(
            inst_id="BTC-USDT-SWAP",
            position="long 1.5",
            balance=Decimal("10000"),
            current_price=Decimal("50000"),
            risk_per_trade=Decimal("0.01"),
            analyst_output="建议开多仓",
        )
        assert "BTC-USDT-SWAP" in formatted
        assert "10000" in formatted
        assert "50000" in formatted
        assert "0.01" in formatted


class TestModelSerialization:
    """模型序列化/反序列化测试"""

    def test_kline_json_roundtrip(self):
        """测试K线JSON往返序列化"""
        original = Kline(
            timestamp=1704067200000,
            open=Decimal("42000.00"),
            high=Decimal("43000.00"),
            low=Decimal("41000.00"),
            close=Decimal("42500.00"),
            vol=Decimal("100.5"),
            confirm=1,
        )
        json_str = original.model_dump_json()
        restored = Kline.model_validate_json(json_str)
        assert restored.timestamp == original.timestamp
        assert restored.open == original.open

    def test_position_json_roundtrip(self):
        """测试仓位JSON往返序列化"""
        original = Position(
            inst_id="BTC-USDT-SWAP",
            direction=PositionDirection.LONG,
            size=Decimal("1.5"),
            entry_price=Decimal("42000.00"),
        )
        json_str = original.model_dump_json()
        restored = Position.model_validate_json(json_str)
        assert restored.inst_id == original.inst_id
        assert restored.direction == original.direction

    def test_trade_instruction_json_roundtrip(self):
        """测试交易指令JSON往返序列化"""
        original = TradeInstruction(
            op=TradeOperation.ENTRY_LONG,
            args={"size": "100", "stop_loss": "40000", "take_profit": "45000"},
        )
        json_str = original.model_dump_json()
        restored = TradeInstruction.model_validate_json(json_str)
        assert restored.op == original.op
        assert restored.args["size"] == "100"

    def test_trade_record_json_roundtrip(self):
        """测试交易记录JSON往返序列化"""
        original = TradeRecord(
            timestamp=1704067200000,
            inst_id="BTC-USDT-SWAP",
            position_direction=PositionDirection.LONG,
            position_size=Decimal("1.5"),
            entry_avg_price=Decimal("42000.00"),
            exit_avg_price=Decimal("43000.00"),
            realized_pnl=Decimal("1500"),
            balance_after_close=Decimal("10000"),
            order_id="123456789",
        )
        json_str = original.model_dump_json()
        restored = TradeRecord.model_validate_json(json_str)
        assert restored.inst_id == original.inst_id
        assert restored.realized_pnl == original.realized_pnl

    def test_config_json_roundtrip(self):
        """测试配置JSON往返序列化"""
        original = Config(
            global_config=GlobalConfig(
                demo_mode=True,
                log_level="INFO",
                llm_model="gpt-4o",
            ),
            trade_pairs=[
                TradePairConfig(
                    inst_id="BTC-USDT-SWAP",
                    timeframe="1H",
                    leverage=10,
                    position_size=Decimal("100"),
                    stop_loss_ratio=Decimal("0.02"),
                    take_profit_ratio=Decimal("0.05"),
                ),
            ],
        )
        json_str = original.model_dump_json()
        restored = Config.model_validate_json(json_str)
        assert restored.global_config.demo_mode == original.global_config.demo_mode
        assert len(restored.trade_pairs) == len(original.trade_pairs)
