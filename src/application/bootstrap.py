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
        self.logger.info("开始启动自检...")

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

            self.logger.info("所有启动自检通过!")
            return True

        except ConfigError as e:
            self.logger.fatal(f"配置错误: {e}")
            sys.exit(self.EXIT_CONFIG_ERROR)

        except OKXAPIError as e:
            self.logger.fatal(f"OKX连接错误: {e}")
            sys.exit(self.EXIT_CONNECTION_ERROR)

        except LLMError as e:
            self.logger.fatal(f"LLM连接错误: {e}")
            sys.exit(self.EXIT_CONNECTION_ERROR)

        except Exception as e:
            self.logger.fatal(f"启动自检期间发生意外错误: {e}")
            sys.exit(self.EXIT_CONNECTION_ERROR)

    async def _check_config(self):
        """检查配置"""
        self.logger.info("检查配置...")

        # 检查OKX配置
        if not self.config.okx_api_key:
            raise ConfigError("缺少OKX API密钥")
        if not self.config.okx_api_secret:
            raise ConfigError("缺少OKX API密钥")
        if not self.config.okx_passphrase:
            raise ConfigError("缺少OKX密码")

        # 检查LLM配置
        if not self.config.openai_api_key:
            raise ConfigError("缺少OpenAI API密钥")

        # 检查交易对配置
        if not self.config.trade_pairs:
            raise ConfigError("未配置交易对")

        # 检查Prompt配置
        for key in ["analyst", "trader", "compressor"]:
            if key not in self.config.prompts:
                raise ConfigError(f"缺少{key}的Prompt配置")

        self.logger.info("配置检查通过")

    async def _check_okx_connection(self):
        """检查OKX连接"""
        self.logger.info("检查OKX连接...")

        self.okx_client = OKXRestClient(
            api_key=self.config.okx_api_key,
            api_secret=self.config.okx_api_secret,
            passphrase=self.config.okx_passphrase,
            demo_mode=self.config.global_config.demo_mode,
        )

        # 尝试查询余额验证连接
        try:
            balance = await self.okx_client.get_balance("USDT")
            self.logger.info(f"OKX连接成功, 余额: {balance}")
        except Exception as e:
            raise OKXAPIError(f"连接OKX失败: {e}")

        # 验证交易对合法性
        for pair in self.config.trade_pairs:
            try:
                info = await self.okx_client.get_instrument_info(pair.inst_id)
                self.logger.info(f"交易对 {pair.inst_id} 有效: {info.get('instId')}")
            except Exception as e:
                raise OKXAPIError(f"无效的交易对 {pair.inst_id}: {e}")

    async def _check_position_mode(self):
        """检查并设置持仓模式"""
        self.logger.info("检查持仓模式...")

        # 设置单向持仓模式
        try:
            result = await self.okx_client.set_position_mode("net")
            self.logger.info(f"持仓模式设置为单向: {result}")
        except Exception as e:
            # 可能已经设置过了，忽略错误
            self.logger.warning(f"设置持仓模式失败(可能已设置): {e}")

        # 设置每个交易对的杠杆
        for pair in self.config.trade_pairs:
            try:
                result = await self.okx_client.set_leverage(
                    inst_id=pair.inst_id,
                    lever=pair.leverage,
                    mgn_mode=self.config.global_config.td_mode,
                )
                self.logger.info(f"杠杆设置完成 {pair.inst_id}: {result}")
            except Exception as e:
                self.logger.warning(
                    f"设置杠杆失败 {pair.inst_id} (可能已设置): {e}"
                )

    async def _check_llm_connection(self):
        """检查LLM连接"""
        self.logger.info("检查LLM连接...")

        self.llm_client = LLMClient(
            api_key=self.config.openai_api_key,
            base_url=self.config.openai_base_url,
            model=self.config.global_config.llm_model,
        )

        # 尝试发送测试请求
        is_connected = await self.llm_client.test_connection()
        if not is_connected:
            raise LLMError("连接LLM API失败")

        self.logger.info("LLM连接成功")

    async def _check_llm_vision(self):
        """检查LLM图片解析能力"""
        self.logger.info("检查LLM图片解析能力...")

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
            raise LLMError("LLM图片解析能力不可用")

        self.logger.info("LLM图片解析能力检查通过")

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
