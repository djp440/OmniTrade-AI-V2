"""配置加载组件单元测试。"""

import os
import tempfile
from pathlib import Path

import pytest

from src.infrastructure.config_loader import (
    AppConfig,
    ConfigContainer,
    GlobalConfig,
    OkxCredentials,
    PromptConfig,
    TradePairConfig,
    load_config,
    load_env_config,
    parse_toml_config,
    validate_config,
)


class TestLoadEnvConfig:
    """测试.env配置加载。"""

    def test_load_env_from_file(self):
        """测试从文件加载.env配置。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False, encoding="utf-8") as f:
            f.write("OKX_REAL_API_KEY=test_key\n")
            f.write("OKX_REAL_API_SECRET=test_secret\n")
            f.write("OKX_REAL_PASSPHRASE=test_pass\n")
            f.write("OKX_DEMO_API_KEY=demo_key\n")
            f.write("OKX_DEMO_API_SECRET=demo_secret\n")
            f.write("OKX_DEMO_PASSPHRASE=demo_pass\n")
            f.write("OPENAI_API_KEY=sk-test\n")
            f.write("OPENAI_BASE_URL=https://test.com/v1\n")
            temp_path = f.name

        try:
            config = load_env_config(temp_path)
            assert config["OKX_REAL_API_KEY"] == "test_key"
            assert config["OKX_REAL_API_SECRET"] == "test_secret"
            assert config["OKX_REAL_PASSPHRASE"] == "test_pass"
            assert config["OKX_DEMO_API_KEY"] == "demo_key"
            assert config["OPENAI_API_KEY"] == "sk-test"
            assert config["OPENAI_BASE_URL"] == "https://test.com/v1"
        finally:
            os.unlink(temp_path)

    def test_load_env_default_base_url(self):
        """测试默认OpenAI Base URL。"""
        env_vars_before = dict(os.environ)
        try:
            for key in list(os.environ.keys()):
                if key.startswith("OPENAI_"):
                    del os.environ[key]

            with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False, encoding="utf-8") as f:
                f.write("OPENAI_API_KEY=sk-test\n")
                temp_path = f.name

            try:
                config = load_env_config(temp_path)
                assert config["OPENAI_BASE_URL"] == "https://api.openai.com/v1"
            finally:
                os.unlink(temp_path)
        finally:
            os.environ.clear()
            os.environ.update(env_vars_before)


class TestParseTomlConfig:
    """测试TOML配置解析。"""

    def test_parse_valid_config_toml(self):
        """测试解析有效的config.toml。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False, encoding="utf-8") as f:
            f.write('[global]\n')
            f.write('demo_mode = true\n')
            f.write('log_level = "INFO"\n')
            f.write('log_dir = "./logs"\n')
            f.write('\n')
            f.write('[[trade_pairs]]\n')
            f.write('inst_id = "BTC-USDT-SWAP"\n')
            f.write('timeframe = "1H"\n')
            f.write('leverage = 10\n')
            f.write('position_size = 100\n')
            f.write('stop_loss_ratio = 0.02\n')
            f.write('take_profit_ratio = 0.05\n')
            temp_path = f.name

        try:
            data = parse_toml_config(temp_path)
            assert data["global"]["demo_mode"] is True
            assert data["global"]["log_level"] == "INFO"
            assert len(data["trade_pairs"]) == 1
            assert data["trade_pairs"][0]["inst_id"] == "BTC-USDT-SWAP"
        finally:
            os.unlink(temp_path)

    def test_parse_valid_prompt_toml(self):
        """测试解析有效的prompt.toml。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False, encoding="utf-8") as f:
            f.write('[analyst]\n')
            f.write('system_prompt = "Analyst prompt"\n')
            f.write('\n')
            f.write('[trader]\n')
            f.write('system_prompt = "Trader prompt"\n')
            f.write('\n')
            f.write('[compressor]\n')
            f.write('system_prompt = "Compressor prompt"\n')
            temp_path = f.name

        try:
            data = parse_toml_config(temp_path)
            assert data["analyst"]["system_prompt"] == "Analyst prompt"
            assert data["trader"]["system_prompt"] == "Trader prompt"
            assert data["compressor"]["system_prompt"] == "Compressor prompt"
        finally:
            os.unlink(temp_path)

    def test_parse_nonexistent_file(self):
        """测试解析不存在的文件。"""
        with pytest.raises(FileNotFoundError):
            parse_toml_config("nonexistent.toml")

    def test_parse_invalid_toml(self):
        """测试解析无效的TOML。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False, encoding="utf-8") as f:
            f.write("invalid toml content [[\n")
            temp_path = f.name

        try:
            with pytest.raises(ValueError):
                parse_toml_config(temp_path)
        finally:
            os.unlink(temp_path)


class TestGlobalConfig:
    """测试全局配置模型。"""

    def test_valid_global_config(self):
        """测试有效的全局配置。"""
        config = GlobalConfig(
            demo_mode=True,
            log_level="DEBUG",
            log_dir="./logs",
            max_analysis_history_length=20,
            k_line_count=50,
        )
        assert config.demo_mode is True
        assert config.log_level == "DEBUG"

    def test_invalid_log_level(self):
        """测试无效的日志级别。"""
        with pytest.raises(ValueError):
            GlobalConfig(log_level="INVALID")

    def test_invalid_td_mode(self):
        """测试无效的持仓模式。"""
        with pytest.raises(ValueError):
            GlobalConfig(td_mode="invalid")

    def test_log_level_case_insensitive(self):
        """测试日志级别大小写不敏感。"""
        config = GlobalConfig(log_level="info")
        assert config.log_level == "INFO"


class TestTradePairConfig:
    """测试交易对配置模型。"""

    def test_valid_trade_pair(self):
        """测试有效的交易对配置。"""
        config = TradePairConfig(
            inst_id="BTC-USDT-SWAP",
            timeframe="1H",
            leverage=10,
            position_size=100,
            stop_loss_ratio=0.02,
            take_profit_ratio=0.05,
        )
        assert config.inst_id == "BTC-USDT-SWAP"
        assert config.timeframe == "1H"

    def test_invalid_timeframe(self):
        """测试无效的K线周期。"""
        with pytest.raises(ValueError):
            TradePairConfig(
                inst_id="BTC-USDT-SWAP",
                timeframe="INVALID",
                leverage=10,
                position_size=100,
                stop_loss_ratio=0.02,
                take_profit_ratio=0.05,
            )

    def test_leverage_out_of_range(self):
        """测试杠杆倍数超出范围。"""
        with pytest.raises(ValueError):
            TradePairConfig(
                inst_id="BTC-USDT-SWAP",
                timeframe="1H",
                leverage=200,
                position_size=100,
                stop_loss_ratio=0.02,
                take_profit_ratio=0.05,
            )


class TestLoadConfig:
    """测试完整配置加载。"""

    def test_load_complete_config(self):
        """测试加载完整配置。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            config_toml_path = Path(tmpdir) / "config.toml"
            prompt_toml_path = Path(tmpdir) / "prompt.toml"

            env_path.write_text("""
OKX_REAL_API_KEY=real_key
OKX_REAL_API_SECRET=real_secret
OKX_REAL_PASSPHRASE=real_pass
OKX_DEMO_API_KEY=demo_key
OKX_DEMO_API_SECRET=demo_secret
OKX_DEMO_PASSPHRASE=demo_pass
OPENAI_API_KEY=sk-test
""", encoding="utf-8")

            config_toml_path.write_text("""
[global]
demo_mode = true
log_level = "INFO"
log_dir = "./logs"
max_analysis_history_length = 10
k_line_count = 100
llm_model = "gpt-4o"
trade_record_path = "./trade_records.csv"
td_mode = "isolated"

[[trade_pairs]]
inst_id = "BTC-USDT-SWAP"
timeframe = "1H"
leverage = 10
position_size = 100
stop_loss_ratio = 0.02
take_profit_ratio = 0.05
""", encoding="utf-8")

            prompt_toml_path.write_text("""
[analyst]
system_prompt = "Analyst prompt"

[trader]
system_prompt = "Trader prompt"

[compressor]
system_prompt = "Compressor prompt"
""", encoding="utf-8")

            container = load_config(env_path, config_toml_path, prompt_toml_path)

            assert container.okx_real is not None
            assert container.okx_real.api_key == "real_key"
            assert container.okx_demo is not None
            assert container.okx_demo.api_key == "demo_key"
            assert container.openai_api_key == "sk-test"
            assert container.app_config is not None
            assert len(container.app_config.trade_pairs) == 1
            assert container.prompt_config is not None
            assert container.prompt_config.analyst == "Analyst prompt"

    def test_load_config_no_trade_pairs(self):
        """测试没有交易对配置时抛出异常。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            config_toml_path = Path(tmpdir) / "config.toml"
            prompt_toml_path = Path(tmpdir) / "prompt.toml"

            env_path.write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")
            config_toml_path.write_text("[global]\ndemo_mode = true\n", encoding="utf-8")
            prompt_toml_path.write_text('[analyst]\nsystem_prompt = "test"\n', encoding="utf-8")

            with pytest.raises(ValueError, match="必须至少配置一个交易对"):
                load_config(env_path, config_toml_path, prompt_toml_path)


class TestValidateConfig:
    """测试配置验证。"""

    def test_valid_config(self):
        """测试有效配置验证通过。"""
        container = ConfigContainer()
        container.okx_real = OkxCredentials(
            api_key="key", api_secret="secret", passphrase="pass"
        )
        container.okx_demo = OkxCredentials(
            api_key="key", api_secret="secret", passphrase="pass"
        )
        container.openai_api_key = "sk-test"
        container.app_config = AppConfig(
            global_config=GlobalConfig(),
            trade_pairs=[TradePairConfig(
                inst_id="BTC-USDT-SWAP",
                timeframe="1H",
                leverage=10,
                position_size=100,
                stop_loss_ratio=0.02,
                take_profit_ratio=0.05,
            )],
        )
        container.prompt_config = PromptConfig(
            analyst="analyst prompt",
            trader="trader prompt",
            compressor="compressor prompt",
        )

        validate_config(container)

    def test_missing_okx_real(self):
        """测试缺少OKX实盘凭证。"""
        container = ConfigContainer()
        container.okx_demo = OkxCredentials(
            api_key="key", api_secret="secret", passphrase="pass"
        )
        container.openai_api_key = "sk-test"

        with pytest.raises(ValueError, match="缺少OKX实盘凭证"):
            validate_config(container)

    def test_missing_openai_key(self):
        """测试缺少OpenAI API Key。"""
        container = ConfigContainer()
        container.okx_real = OkxCredentials(
            api_key="key", api_secret="secret", passphrase="pass"
        )
        container.okx_demo = OkxCredentials(
            api_key="key", api_secret="secret", passphrase="pass"
        )

        with pytest.raises(ValueError, match="缺少OpenAI API Key"):
            validate_config(container)

    def test_empty_prompt(self):
        """测试空的Prompt配置。"""
        container = ConfigContainer()
        container.okx_real = OkxCredentials(
            api_key="key", api_secret="secret", passphrase="pass"
        )
        container.okx_demo = OkxCredentials(
            api_key="key", api_secret="secret", passphrase="pass"
        )
        container.openai_api_key = "sk-test"
        container.app_config = AppConfig(
            global_config=GlobalConfig(),
            trade_pairs=[TradePairConfig(
                inst_id="BTC-USDT-SWAP",
                timeframe="1H",
                leverage=10,
                position_size=100,
                stop_loss_ratio=0.02,
                take_profit_ratio=0.05,
            )],
        )
        container.prompt_config = PromptConfig(analyst="", trader="", compressor="")

        with pytest.raises(ValueError, match="分析师Prompt不能为空"):
            validate_config(container)
