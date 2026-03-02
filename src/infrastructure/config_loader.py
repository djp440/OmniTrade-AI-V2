"""配置加载组件，支持.env、config.toml、prompt.toml的加载和验证。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


class OkxCredentials(BaseModel):
    """OKX API凭证配置。"""

    api_key: str = Field(..., description="OKX API Key")
    api_secret: str = Field(..., description="OKX API Secret")
    passphrase: str = Field(..., description="OKX API Passphrase")


class TradePairConfig(BaseModel):
    """交易对配置。"""

    inst_id: str = Field(..., description="交易对ID，如 BTC-USDT-SWAP")
    timeframe: str = Field(..., description="K线周期，如 1H, 4H, 1D")
    leverage: int = Field(..., ge=1, le=125, description="杠杆倍数")
    position_size: float = Field(..., gt=0, description="开仓名义金额（USDT）")
    stop_loss_ratio: float = Field(..., gt=0, lt=1, description="止损比例")
    take_profit_ratio: float = Field(..., gt=0, lt=1, description="止盈比例")

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, v: str) -> str:
        valid_timeframes = {"1m", "5m", "15m", "30m", "1H", "2H", "4H", "6H", "12H", "1D", "1W", "1M"}
        if v not in valid_timeframes:
            raise ValueError(f"无效的timeframe: {v}，必须是以下之一: {valid_timeframes}")
        return v


class GlobalConfig(BaseModel):
    """全局配置。"""

    demo_mode: bool = Field(default=True, description="模拟盘开关")
    log_level: str = Field(default="INFO", description="日志级别")
    log_dir: str = Field(default="./logs", description="日志目录")
    max_analysis_history_length: int = Field(default=10, ge=1, description="分析历史最大保留条数")
    k_line_count: int = Field(default=100, ge=1, le=1000, description="每次获取的历史K线数量")
    llm_model: str = Field(default="gpt-4o", description="LLM模型名称")
    trade_record_path: str = Field(default="./trade_records.csv", description="交易记录CSV路径")
    td_mode: str = Field(default="isolated", description="持仓模式: isolated/cross")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "FATAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"无效的log_level: {v}，必须是以下之一: {valid_levels}")
        return v_upper

    @field_validator("td_mode")
    @classmethod
    def validate_td_mode(cls, v: str) -> str:
        if v not in {"isolated", "cross"}:
            raise ValueError(f"无效的td_mode: {v}，必须是 'isolated' 或 'cross'")
        return v


class AppConfig(BaseModel):
    """应用程序完整配置。"""

    global_config: GlobalConfig
    trade_pairs: list[TradePairConfig]


class PromptConfig(BaseModel):
    """Prompt配置。"""

    analyst: str = Field(..., description="分析师System Prompt")
    trader: str = Field(..., description="交易员System Prompt")
    compressor: str = Field(..., description="压缩者System Prompt")


@dataclass
class ConfigContainer:
    """配置容器，包含所有配置信息。"""

    okx_real: OkxCredentials | None = None
    okx_demo: OkxCredentials | None = None
    openai_api_key: str = ""
    openai_base_url: str = ""
    app_config: AppConfig | None = None
    prompt_config: PromptConfig | None = None


def load_env_config(env_path: str | Path = ".env") -> dict[str, str]:
    """加载.env文件配置。

    Args:
        env_path: .env文件路径

    Returns:
        包含环境变量的字典
    """
    env_file = Path(env_path)
    if env_file.exists():
        load_dotenv(env_file, override=True)

    config = {}
    required_keys = [
        "OKX_REAL_API_KEY",
        "OKX_REAL_API_SECRET",
        "OKX_REAL_PASSPHRASE",
        "OKX_DEMO_API_KEY",
        "OKX_DEMO_API_SECRET",
        "OKX_DEMO_PASSPHRASE",
        "OPENAI_API_KEY",
    ]

    for key in required_keys:
        value = os.getenv(key)
        if value:
            config[key] = value

    config["OPENAI_BASE_URL"] = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    return config


def parse_toml_config(toml_path: str | Path) -> dict[str, Any]:
    """解析TOML配置文件。

    Args:
        toml_path: TOML文件路径

    Returns:
        解析后的配置字典

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: 解析失败
    """
    file_path = Path(toml_path)
    if not file_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {toml_path}")

    try:
        with open(file_path, "rb") as f:
            return tomli.load(f)
    except tomli.TOMLDecodeError as e:
        raise ValueError(f"TOML解析失败: {e}") from e


def load_config(
    env_path: str | Path = ".env",
    config_toml_path: str | Path = "config/config.toml",
    prompt_toml_path: str | Path = "config/prompt.toml",
) -> ConfigContainer:
    """加载所有配置。

    Args:
        env_path: .env文件路径
        config_toml_path: config.toml文件路径
        prompt_toml_path: prompt.toml文件路径

    Returns:
        配置容器对象

    Raises:
        FileNotFoundError: 配置文件不存在
        ValueError: 配置验证失败
    """
    container = ConfigContainer()

    env_data = load_env_config(env_path)

    if "OKX_REAL_API_KEY" in env_data:
        container.okx_real = OkxCredentials(
            api_key=env_data["OKX_REAL_API_KEY"],
            api_secret=env_data["OKX_REAL_API_SECRET"],
            passphrase=env_data["OKX_REAL_PASSPHRASE"],
        )

    if "OKX_DEMO_API_KEY" in env_data:
        container.okx_demo = OkxCredentials(
            api_key=env_data["OKX_DEMO_API_KEY"],
            api_secret=env_data["OKX_DEMO_API_SECRET"],
            passphrase=env_data["OKX_DEMO_PASSPHRASE"],
        )

    container.openai_api_key = env_data.get("OPENAI_API_KEY", "")
    container.openai_base_url = env_data.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    config_data = parse_toml_config(config_toml_path)
    global_config = GlobalConfig(**config_data.get("global", {}))

    trade_pairs_data = config_data.get("trade_pairs", [])
    if not trade_pairs_data:
        raise ValueError("配置文件中必须至少配置一个交易对")

    trade_pairs = [TradePairConfig(**pair) for pair in trade_pairs_data]
    container.app_config = AppConfig(global_config=global_config, trade_pairs=trade_pairs)

    prompt_data = parse_toml_config(prompt_toml_path)
    container.prompt_config = PromptConfig(
        analyst=prompt_data.get("analyst", {}).get("system_prompt", ""),
        trader=prompt_data.get("trader", {}).get("system_prompt", ""),
        compressor=prompt_data.get("compressor", {}).get("system_prompt", ""),
    )

    return container


def validate_config(container: ConfigContainer) -> None:
    """验证配置完整性。

    Args:
        container: 配置容器

    Raises:
        ValueError: 配置验证失败
    """
    errors = []

    if not container.okx_real:
        errors.append("缺少OKX实盘凭证配置")
    if not container.okx_demo:
        errors.append("缺少OKX模拟盘凭证配置")
    if not container.openai_api_key:
        errors.append("缺少OpenAI API Key")
    if not container.app_config:
        errors.append("缺少应用配置")
    if not container.prompt_config:
        errors.append("缺少Prompt配置")

    if container.prompt_config:
        if not container.prompt_config.analyst:
            errors.append("分析师Prompt不能为空")
        if not container.prompt_config.trader:
            errors.append("交易员Prompt不能为空")
        if not container.prompt_config.compressor:
            errors.append("压缩者Prompt不能为空")

    if errors:
        raise ValueError("配置验证失败:\n" + "\n".join(f"  - {e}" for e in errors))
