"""
启动自检流程
"""

import sys
from datetime import datetime

from src.infrastructure.config_loader import AppConfig, ConfigError, load_config
from src.infrastructure.llm_client import LLMClient, LLMError
from src.infrastructure.logger import Logger, get_logger
from src.infrastructure.okx_client import OKXAPIError, OKXRestClient
from src.infrastructure.utils import TradeRecordStorage, generate_kline_chart


class Bootstrap:
    """启动自检"""

    EXIT_CONFIG_ERROR = 2
    EXIT_CONNECTION_ERROR = 3

    def __init__(self, config: AppConfig, logger: Logger):
        self.config = config
        self.logger = logger
        self.okx_client: OKXRestClient | None = None
        self.llm_client: LLMClient | None = None

    async def run(self) -> bool:
        """
        运行启动自检

        Returns:
            是否通过自检
        """
        self.logger.info("Starting bootstrap checks...")

        try:
            # 1. 加载配置
            await self._check_config()

            # 2. 初始化OKX客户端并验证连接
            await self._check_okx_connection()

            # 3. 设置持仓模式和杠杆
            await self._check_position_mode()

            # 4. 初始化LLM客户端并验证连接
            await self._check_llm_connection()

            # 5. 验证LLM图片解析能力
            await self._check_llm_vision()

            self.logger.info("All bootstrap checks passed!")
            return True

        except ConfigError as e:
            self.logger.fatal(f"Configuration error: {e}")
            sys.exit(self.EXIT_CONFIG_ERROR)

        except OKXAPIError as e:
            self.logger.fatal(f"OKX connection error: {e}")
            sys.exit(self.EXIT_CONNECTION_ERROR)

        except LLMError as e:
            self.logger.fatal(f"LLM connection error: {e}")
            sys.exit(self.EXIT_CONNECTION_ERROR)

        except Exception as e:
            self.logger.fatal(f"Unexpected error during bootstrap: {e}")
            sys.exit(self.EXIT_CONNECTION_ERROR)

    async def _check_config(self):
        """检查配置"""
        self.logger.info("Checking configuration...")

        # 检查OKX配置
        if not self.config.okx_api_key:
            raise ConfigError("OKX API key is missing")
        if not self.config.okx_api_secret:
            raise ConfigError("OKX API secret is missing")
        if not self.config.okx_passphrase:
            raise ConfigError("OKX passphrase is missing")

        # 检查LLM配置
        if not self.config.openai_api_key:
            raise ConfigError("OpenAI API key is missing")

        # 检查交易对配置
        if not self.config.trade_pairs:
            raise ConfigError("No trade pairs configured")

        # 检查Prompt配置
        for key in ["analyst", "trader", "compressor"]:
            if key not in self.config.prompts:
                raise ConfigError(f"Missing prompt for {key}")

        self.logger.info("Configuration check passed")

    async def _check_okx_connection(self):
        """检查OKX连接"""
        self.logger.info("Checking OKX connection...")

        self.okx_client = OKXRestClient(
            api_key=self.config.okx_api_key,
            api_secret=self.config.okx_api_secret,
            passphrase=self.config.okx_passphrase,
            demo_mode=self.config.global_config.demo_mode,
        )

        # 尝试查询余额验证连接
        try:
            balance = await self.okx_client.get_balance("USDT")
            self.logger.info(f"OKX connection successful, balance: {balance}")
        except Exception as e:
            raise OKXAPIError(f"Failed to connect to OKX: {e}")

        # 验证交易对合法性
        for pair in self.config.trade_pairs:
            try:
                info = await self.okx_client.get_instrument_info(pair.inst_id)
                self.logger.info(f"Trade pair {pair.inst_id} is valid: {info.get('instId')}")
            except Exception as e:
                raise OKXAPIError(f"Invalid trade pair {pair.inst_id}: {e}")

    async def _check_position_mode(self):
        """检查并设置持仓模式"""
        self.logger.info("Checking position mode...")

        # 设置单向持仓模式
        try:
            result = await self.okx_client.set_position_mode("net")
            self.logger.info(f"Position mode set to net: {result}")
        except Exception as e:
            # 可能已经设置过了，忽略错误
            self.logger.warning(f"Failed to set position mode (may already be set): {e}")

        # 设置每个交易对的杠杆
        for pair in self.config.trade_pairs:
            try:
                result = await self.okx_client.set_leverage(
                    inst_id=pair.inst_id,
                    lever=pair.leverage,
                    mgn_mode=self.config.global_config.td_mode,
                )
                self.logger.info(f"Leverage set for {pair.inst_id}: {result}")
            except Exception as e:
                self.logger.warning(
                    f"Failed to set leverage for {pair.inst_id} (may already be set): {e}"
                )

    async def _check_llm_connection(self):
        """检查LLM连接"""
        self.logger.info("Checking LLM connection...")

        self.llm_client = LLMClient(
            api_key=self.config.openai_api_key,
            base_url=self.config.openai_base_url,
            model=self.config.global_config.llm_model,
        )

        # 尝试发送测试请求
        is_connected = await self.llm_client.test_connection()
        if not is_connected:
            raise LLMError("Failed to connect to LLM API")

        self.logger.info("LLM connection successful")

    async def _check_llm_vision(self):
        """检查LLM图片解析能力"""
        self.logger.info("Checking LLM vision capability...")

        # 创建一个简单的测试K线图
        test_klines = [
            {
                "timestamp": int(datetime.now().timestamp() * 1000) - i * 3600000,
                "open": 50000 + i * 100,
                "high": 50100 + i * 100,
                "low": 49900 + i * 100,
                "close": 50050 + i * 100,
            }
            for i in range(25, 0, -1)
        ]

        ema_values = [50000 + i * 100 for i in range(25)]

        img_base64 = generate_kline_chart(
            klines=test_klines,
            ema_values=ema_values,
            inst_id="TEST-USDT",
            timeframe="1H",
        )

        # 测试图片解析
        is_vision_working = await self.llm_client.test_vision()
        if not is_vision_working:
            raise LLMError("LLM vision capability is not working")

        self.logger.info("LLM vision capability check passed")

    def get_okx_client(self) -> OKXRestClient:
        """获取已初始化的OKX客户端"""
        return self.okx_client

    def get_llm_client(self) -> LLMClient:
        """获取已初始化的LLM客户端"""
        return self.llm_client


async def run_bootstrap(config: AppConfig, logger: Logger) -> Bootstrap:
    """
    运行启动自检的便捷函数

    Args:
        config: 应用配置
        logger: 日志器

    Returns:
        Bootstrap实例
    """
    bootstrap = Bootstrap(config, logger)
    await bootstrap.run()
    return bootstrap
