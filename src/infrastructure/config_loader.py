"""
配置加载组件
支持.env和TOML文件加载
"""

import os
from dataclasses import dataclass, field
from typing import Any, Optional

import tomli
from dotenv import load_dotenv


@dataclass
class TradePairConfig:
    """交易对配置"""

    inst_id: str
    timeframe: str
    leverage: int
    position_size: float
    stop_loss_ratio: float
    take_profit_ratio: float


@dataclass
class GlobalConfig:
    """全局配置"""

    demo_mode: bool = True
    log_level: str = "INFO"
    log_dir: str = "./logs"
    max_analysis_history_length: int = 10
    k_line_count: int = 100
    llm_model: str = "gpt-4o"
    trade_record_path: str = "./trade_records.csv"
    td_mode: str = "isolated"
    risk_per_trade: float = 0.01


@dataclass
class AppConfig:
    """应用配置"""

    global_config: GlobalConfig = field(default_factory=GlobalConfig)
    trade_pairs: list[TradePairConfig] = field(default_factory=list)
    prompts: dict[str, str] = field(default_factory=dict)

    # OKX配置
    okx_api_key: str = ""
    okx_api_secret: str = ""
    okx_passphrase: str = ""

    # LLM配置
    openai_api_key: str = ""
    openai_base_url: Optional[str] = None


class ConfigLoader:
    """配置加载器"""

    def __init__(
        self,
        env_path: str = ".env",
        config_path: str = "config/config.toml",
        prompt_path: str = "config/prompt.toml",
    ):
        self.env_path = env_path
        self.config_path = config_path
        self.prompt_path = prompt_path

    def load(self) -> AppConfig:
        """加载所有配置"""
        config = AppConfig()

        # 加载.env
        self._load_env(config)

        # 加载config.toml
        self._load_toml_config(config)

        # 加载prompt.toml
        self._load_prompts(config)

        return config

    def _load_env(self, config: AppConfig):
        """加载环境变量"""
        load_dotenv(self.env_path)

        demo_mode = os.getenv("DEMO_MODE", "true").lower() == "true"

        if demo_mode:
            config.okx_api_key = os.getenv("OKX_DEMO_API_KEY", "")
            config.okx_api_secret = os.getenv("OKX_DEMO_API_SECRET", "")
            config.okx_passphrase = os.getenv("OKX_DEMO_PASSPHRASE", "")
        else:
            config.okx_api_key = os.getenv("OKX_REAL_API_KEY", "")
            config.okx_api_secret = os.getenv("OKX_REAL_API_SECRET", "")
            config.okx_passphrase = os.getenv("OKX_REAL_PASSPHRASE", "")

        config.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        config.openai_base_url = os.getenv("OPENAI_BASE_URL")

    def _load_toml_config(self, config: AppConfig):
        """加载TOML配置文件"""
        if not os.path.exists(self.config_path):
            raise ConfigError(f"Config file not found: {self.config_path}")

        with open(self.config_path, "rb") as f:
            data = tomli.load(f)

        # 加载全局配置
        if "global" in data:
            global_data = data["global"]
            config.global_config = GlobalConfig(
                demo_mode=global_data.get("demo_mode", True),
                log_level=global_data.get("log_level", "INFO"),
                log_dir=global_data.get("log_dir", "./logs"),
                max_analysis_history_length=global_data.get(
                    "max_analysis_history_length", 10
                ),
                k_line_count=global_data.get("k_line_count", 100),
                llm_model=global_data.get("llm_model", "gpt-4o"),
                trade_record_path=global_data.get(
                    "trade_record_path", "./trade_records.csv"
                ),
                td_mode=global_data.get("td_mode", "isolated"),
                risk_per_trade=global_data.get("risk_per_trade", 0.01),
            )

        # 加载交易对配置
        if "trade_pairs" in data:
            for pair_data in data["trade_pairs"]:
                trade_pair = TradePairConfig(
                    inst_id=pair_data["inst_id"],
                    timeframe=pair_data["timeframe"],
                    leverage=pair_data["leverage"],
                    position_size=pair_data["position_size"],
                    stop_loss_ratio=pair_data["stop_loss_ratio"],
                    take_profit_ratio=pair_data["take_profit_ratio"],
                )
                config.trade_pairs.append(trade_pair)

    def _load_prompts(self, config: AppConfig):
        """加载Prompt配置"""
        if not os.path.exists(self.prompt_path):
            raise ConfigError(f"Prompt file not found: {self.prompt_path}")

        with open(self.prompt_path, "rb") as f:
            data = tomli.load(f)

        for key in ["analyst", "trader", "compressor"]:
            if key in data:
                prompt_data = data[key]
                if "system_prompt" in prompt_data:
                    config.prompts[key] = prompt_data["system_prompt"]


class ConfigError(Exception):
    """配置错误"""
    pass


def load_config(
    env_path: str = ".env",
    config_path: str = "config/config.toml",
    prompt_path: str = "config/prompt.toml",
) -> AppConfig:
    """
    加载配置的便捷函数

    Args:
        env_path: .env文件路径
        config_path: config.toml文件路径
        prompt_path: prompt.toml文件路径

    Returns:
        AppConfig实例
    """
    loader = ConfigLoader(env_path, config_path, prompt_path)
    return loader.load()
