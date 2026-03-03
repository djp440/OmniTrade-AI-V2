"""启动自检流程

实现启动时的各项检查，包括配置加载、OKX连接、LLM连接等。
所有检查失败直接退出，返回对应退出码。
"""

from __future__ import annotations

import asyncio
import base64
import io
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from src.infrastructure.config_loader import ConfigContainer, load_config
from src.infrastructure.csv_storage import CSVStorage
from src.infrastructure.ema_calculator import EMACalculator
from src.infrastructure.kline_plotter import KlineData, KlinePlotter
from src.infrastructure.llm_client import LLMClient
from src.infrastructure.logger import Logger
from src.infrastructure.okx_auth import OkxCredentials
from src.infrastructure.okx_rest_client import OkxRestClient

if TYPE_CHECKING:
    pass


class StartupCheckError(Exception):
    """启动自检错误"""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class StartupChecker:
    """启动自检器

    执行所有启动前检查，确保配置正确、连接有效。
    """

    EXIT_CONFIG_ERROR = 2
    EXIT_CONNECTION_ERROR = 3

    def __init__(self) -> None:
        """初始化启动自检器"""
        self._logger = Logger()
        self._config: ConfigContainer | None = None
        self._okx_client: OkxRestClient | None = None
        self._llm_client: LLMClient | None = None

    async def run_all_checks(self) -> ConfigContainer:
        """运行所有启动检查

        Returns:
            配置容器对象

        Raises:
            StartupCheckError: 检查失败时抛出，包含退出码
        """
        self._logger.info("=" * 50)
        self._logger.info("启动自检开始...")
        self._logger.info("=" * 50)

        # 1. 加载配置文件
        await self._check_config_loading()

        # 2. 初始化OKX客户端并验证连接
        await self._check_okx_connection()

        # 3. 设置持仓模式和杠杆
        await self._check_position_setup()

        # 4. 初始化LLM客户端并验证连接
        await self._check_llm_connection()

        # 5. 验证LLM图片解析能力
        await self._check_llm_vision()

        self._logger.info("=" * 50)
        self._logger.info("启动自检全部通过！")
        self._logger.info("=" * 50)

        return self._config

    async def _check_config_loading(self) -> None:
        """检查配置加载

        Raises:
            StartupCheckError: 配置加载失败
        """
        self._logger.info("[1/5] 检查配置加载...")

        try:
            env_path = Path(".env")
            config_path = Path("config/config.toml")
            prompt_path = Path("config/prompt.toml")

            # 检查文件是否存在
            if not env_path.exists():
                raise StartupCheckError(
                    f".env文件不存在: {env_path.absolute()}",
                    self.EXIT_CONFIG_ERROR,
                )
            if not config_path.exists():
                raise StartupCheckError(
                    f"config.toml文件不存在: {config_path.absolute()}",
                    self.EXIT_CONFIG_ERROR,
                )
            if not prompt_path.exists():
                raise StartupCheckError(
                    f"prompt.toml文件不存在: {prompt_path.absolute()}",
                    self.EXIT_CONFIG_ERROR,
                )

            self._config = load_config(env_path, config_path, prompt_path)

            # 验证必要配置
            if not self._config.openai_api_key:
                raise StartupCheckError(
                    "OPENAI_API_KEY未配置",
                    self.EXIT_CONFIG_ERROR,
                )

            # 根据模式验证OKX密钥
            if self._config.app_config.global_config.demo_mode:
                if not self._config.okx_demo:
                    raise StartupCheckError(
                        "模拟盘模式需要配置OKX_DEMO_API_KEY等密钥",
                        self.EXIT_CONFIG_ERROR,
                    )
            else:
                if not self._config.okx_real:
                    raise StartupCheckError(
                        "实盘模式需要配置OKX_REAL_API_KEY等密钥",
                        self.EXIT_CONFIG_ERROR,
                    )

            self._logger.info("配置加载成功")

        except StartupCheckError:
            raise
        except Exception as e:
            raise StartupCheckError(
                f"配置加载失败: {e}",
                self.EXIT_CONFIG_ERROR,
            ) from e

    async def _check_okx_connection(self) -> None:
        """检查OKX连接

        Raises:
            StartupCheckError: 连接失败
        """
        self._logger.info("[2/5] 检查OKX连接...")

        try:
            demo_mode = self._config.app_config.global_config.demo_mode
            credentials = (
                self._config.okx_demo
                if demo_mode
                else self._config.okx_real
            )

            self._okx_client = OkxRestClient(
                credentials=credentials,
                is_simulated=demo_mode,
            )

            # 测试连接：查询余额
            balance_response = await self._okx_client.get_balance()
            if balance_response.get("code") != "0":
                raise StartupCheckError(
                    f"OKX余额查询失败: {balance_response.get('msg')}",
                    self.EXIT_CONNECTION_ERROR,
                )

            # 验证所有交易对ID合法性
            for trade_pair in self._config.app_config.trade_pairs:
                inst_info = await self._okx_client.get_instrument(trade_pair.inst_id)
                if inst_info.get("code") != "0":
                    raise StartupCheckError(
                        f"交易对ID无效: {trade_pair.inst_id}",
                        self.EXIT_CONNECTION_ERROR,
                    )
                self._logger.info(f"交易对验证通过: {trade_pair.inst_id}")

            self._logger.info("OKX连接验证成功")

        except StartupCheckError:
            raise
        except Exception as e:
            raise StartupCheckError(
                f"OKX连接验证失败: {e}",
                self.EXIT_CONNECTION_ERROR,
            ) from e

    async def _check_position_setup(self) -> None:
        """检查持仓模式设置

        Raises:
            StartupCheckError: 设置失败
        """
        self._logger.info("[3/5] 检查持仓模式设置...")

        try:
            # 设置单向持仓模式
            result = await self._okx_client.set_position_mode("net_mode")
            if result.get("code") != "0":
                # 检查是否已经是单向持仓
                if "51000" not in str(result.get("msg", "")):
                    raise StartupCheckError(
                        f"设置持仓模式失败: {result.get('msg')}",
                        self.EXIT_CONNECTION_ERROR,
                    )

            self._logger.info("持仓模式已设置为单向持仓")

            # 为每个交易对设置杠杆
            td_mode = self._config.app_config.global_config.td_mode
            for trade_pair in self._config.app_config.trade_pairs:
                result = await self._okx_client.set_leverage(
                    inst_id=trade_pair.inst_id,
                    lever=trade_pair.leverage,
                    mgn_mode=td_mode,
                )
                if result.get("code") != "0":
                    raise StartupCheckError(
                        f"设置杠杆失败: {trade_pair.inst_id}, {result.get('msg')}",
                        self.EXIT_CONNECTION_ERROR,
                    )
                self._logger.info(
                    f"杠杆设置成功: {trade_pair.inst_id} = {trade_pair.leverage}x"
                )

            self._logger.info("持仓模式设置完成")

        except StartupCheckError:
            raise
        except Exception as e:
            raise StartupCheckError(
                f"持仓模式设置失败: {e}",
                self.EXIT_CONNECTION_ERROR,
            ) from e

    async def _check_llm_connection(self) -> None:
        """检查LLM连接

        Raises:
            StartupCheckError: 连接失败
        """
        self._logger.info("[4/5] 检查LLM连接...")

        try:
            self._llm_client = LLMClient(
                api_key=self._config.openai_api_key,
                base_url=self._config.openai_base_url or None,
            )

            # 发送测试文本请求，要求返回"OK"
            response = await self._llm_client.chat(
                model=self._config.app_config.global_config.llm_model,
                system_prompt="你是一个测试助手，请直接回复'OK'。",
                user_message="测试连接",
                temperature=0,
            )

            if "OK" not in response.upper():
                self._logger.warning(f"LLM测试响应异常: {response}")
                # 不强制要求返回OK，只要响应正常即可

            self._logger.info("LLM连接验证成功")

        except Exception as e:
            raise StartupCheckError(
                f"LLM连接验证失败: {e}",
                self.EXIT_CONNECTION_ERROR,
            ) from e

    async def _check_llm_vision(self) -> None:
        """检查LLM图片解析能力

        Raises:
            StartupCheckError: 验证失败
        """
        self._logger.info("[5/5] 检查LLM图片解析能力...")

        try:
            # 生成测试K线图
            test_klines = self._generate_test_klines()
            ema_calc = EMACalculator()
            closes = np.array([k.close for k in test_klines])
            ema_values = ema_calc.calculate(closes, period=20)

            plotter = KlinePlotter()
            png_data = plotter.plot(
                klines=test_klines,
                ema_values=ema_values,
                inst_id="TEST-USDT-SWAP",
                timeframe="1H",
            )

            # 转base64
            image_base64 = base64.b64encode(png_data).decode("utf-8")

            # 发送给LLM要求描述
            response = await self._llm_client.chat(
                model=self._config.app_config.global_config.llm_model,
                system_prompt="你是一个图表分析师，请简要描述这张K线图的趋势。",
                user_message="请描述这张K线图的趋势",
                image_data=image_base64,
                temperature=0,
            )

            if not response or len(response) < 5:
                raise StartupCheckError(
                    "LLM图片解析能力验证失败: 响应异常",
                    self.EXIT_CONNECTION_ERROR,
                )

            self._logger.info("LLM图片解析能力验证成功")

        except StartupCheckError:
            raise
        except Exception as e:
            raise StartupCheckError(
                f"LLM图片解析能力验证失败: {e}",
                self.EXIT_CONNECTION_ERROR,
            ) from e

    def _generate_test_klines(self) -> list[KlineData]:
        """生成测试K线数据

        Returns:
            测试K线数据列表
        """
        klines = []
        base_price = 50000.0

        for i in range(50):
            # 生成随机波动
            change = np.random.normal(0, 0.02)
            open_price = base_price * (1 + change)
            close_price = open_price * (1 + np.random.normal(0, 0.01))
            high_price = max(open_price, close_price) * (1 + abs(np.random.normal(0, 0.005)))
            low_price = min(open_price, close_price) * (1 - abs(np.random.normal(0, 0.005)))

            klines.append(
                KlineData(
                    timestamp=datetime.now(),
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                )
            )

            base_price = close_price

        return klines


def handle_startup_error(error: StartupCheckError) -> None:
    """处理启动错误

    Args:
        error: 启动错误
    """
    logger = Logger()
    logger.error(f"启动自检失败: {error}")
    logger.error(f"程序退出，退出码: {error.exit_code}")
    sys.exit(error.exit_code)
