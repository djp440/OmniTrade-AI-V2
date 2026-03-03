"""主事件循环

实现多交易对并行运行、K线收盘事件处理、优雅关闭等功能。
"""

from __future__ import annotations

import asyncio
import signal
import sys
from decimal import Decimal
from typing import TYPE_CHECKING

from src.domain.config import TradePairConfig
from src.domain.events import KlineCloseEvent, PositionCloseEvent
from src.domain.trading import Position, PositionDirection, TradeInstruction
from src.infrastructure.config_loader import ConfigContainer
from src.infrastructure.csv_storage import CSVStorage
from src.infrastructure.ema_calculator import EMACalculator
from src.infrastructure.kline_plotter import KlineData, KlinePlotter
from src.infrastructure.llm_client import LLMClient
from src.infrastructure.logger import Logger
from src.infrastructure.okx_rest_client import OkxRestClient
from src.infrastructure.okx_ws_client import OkxWebSocketClient
from src.services.agent_service import AgentService
from src.services.history_service import HistoryService
from src.services.kline_service import KlineService
from src.services.trading_service import TradingService

if TYPE_CHECKING:
    pass


class TradingPairRunner:
    """交易对运行器

    每个交易对对应一个独立的运行器，包含独立的协程和状态。
    """

    def __init__(
        self,
        trade_pair_config: TradePairConfig,
        okx_rest_client: OkxRestClient,
        okx_ws_client: OkxWebSocketClient,
        agent_service: AgentService,
        history_service: HistoryService,
        trading_service: TradingService,
        kline_count: int,
        risk_per_trade: Decimal,
    ) -> None:
        """初始化交易对运行器

        Args:
            trade_pair_config: 交易对配置
            okx_rest_client: OKX REST客户端
            okx_ws_client: OKX WebSocket客户端
            agent_service: Agent调度服务
            history_service: 历史记录服务
            trading_service: 交易服务
            kline_count: 获取的历史K线数量
            risk_per_trade: 单笔风险百分比
        """
        self._config = trade_pair_config
        self._rest_client = okx_rest_client
        self._ws_client = okx_ws_client
        self._agent_service = agent_service
        self._history_service = history_service
        self._trading_service = trading_service
        self._kline_count = kline_count
        self._risk_per_trade = risk_per_trade

        self._logger = Logger()
        self._kline_service = KlineService(
            rest_client=okx_rest_client,
            ws_client=okx_ws_client,
            trade_pair_config=trade_pair_config,
            kline_count=kline_count,
        )
        self._plotter = KlinePlotter()
        self._ema_calculator = EMACalculator()

        # 异步互斥锁，防止分析流程重叠
        self._analysis_lock = asyncio.Lock()

    async def start(self) -> None:
        """启动交易对运行器"""
        self._logger.info(f"启动交易对运行器: {self._config.inst_id}")

        # 添加K线收盘事件处理器
        self._kline_service.add_kline_close_handler(self._on_kline_close)

        # 启动K线服务
        await self._kline_service.start()

    async def _on_kline_close(self, event: KlineCloseEvent) -> None:
        """处理K线收盘事件

        Args:
            event: K线收盘事件
        """
        # 尝试获取互斥锁，失败则丢弃本次触发
        if self._analysis_lock.locked():
            self._logger.warning(
                f"分析流程正在进行中，丢弃本次K线收盘事件: {self._config.inst_id}"
            )
            return

        await self._analysis_lock.acquire()

        try:
            await self._run_analysis_flow(event)
        finally:
            self._analysis_lock.release()

    async def _run_analysis_flow(self, event: KlineCloseEvent) -> None:
        """执行分析流程

        Args:
            event: K线收盘事件
        """
        self._logger.info(f"开始分析流程: {self._config.inst_id}")

        try:
            # 1. 并行查询账户余额和当前仓位
            balance_task = self._trading_service.get_account_balance()
            position_task = self._trading_service.get_position(self._config.inst_id)

            balance, position = await asyncio.gather(
                balance_task,
                position_task,
                return_exceptions=True,
            )

            if isinstance(balance, Exception):
                self._logger.error(f"查询余额失败: {balance}")
                return
            if isinstance(position, Exception):
                self._logger.error(f"查询仓位失败: {position}")
                return

            # 2. 获取历史K线数据
            klines_data = await self._fetch_historical_klines()
            if not klines_data:
                self._logger.error("获取历史K线数据失败")
                return

            # 3. 计算EMA20
            closes = [k.close for k in klines_data]
            ema_values = self._ema_calculator.calculate(closes, period=20)

            # 4. 生成K线图base64
            kline_image_base64 = await self._generate_kline_image(klines_data, ema_values)
            if not kline_image_base64:
                self._logger.error("生成K线图失败")
                return

            # 5. 获取分析历史
            analysis_history = self._history_service.get_history(self._config.inst_id)

            # 6. 调用分析师Agent
            analyst_output = await self._agent_service.call_analyst(
                inst_id=self._config.inst_id,
                timeframe=self._config.timeframe,
                kline_image_base64=kline_image_base64,
                analysis_history=analysis_history,
                current_position=position,
                account_balance=balance,
            )

            self._logger.info(f"分析师输出: {analyst_output.analysis_text[:100]}...")

            # 7. 并行调用交易员和压缩者Agent
            current_price = Decimal(str(event.kline.close))

            trader_task = self._agent_service.call_trader(
                inst_id=self._config.inst_id,
                analyst_output=analyst_output,
                current_position=position,
                account_balance=balance,
                current_price=current_price,
                trade_pair_config=self._config,
                risk_per_trade=self._risk_per_trade,
            )

            compressor_task = self._agent_service.call_compressor(
                analyst_output=analyst_output,
            )

            trader_result, compressor_result = await asyncio.gather(
                trader_task,
                compressor_task,
                return_exceptions=True,
            )

            # 8. 处理压缩者输出，存入历史
            if isinstance(compressor_result, Exception):
                self._logger.error(f"压缩者调用失败: {compressor_result}")
            else:
                self._history_service.add_analysis_record(
                    self._config.inst_id,
                    compressor_result.compressed_text,
                )

            # 9. 处理交易员输出，执行交易指令
            if isinstance(trader_result, Exception):
                self._logger.error(f"交易员调用失败: {trader_result}")
                return

            if not trader_result.instructions:
                self._logger.info("无交易指令需要执行")
                return

            # 10. 逐条执行交易指令
            has_close_position = False
            for instruction in trader_result.instructions:
                try:
                    result = await self._trading_service.execute_instruction(
                        instruction=instruction,
                        trade_pair_config=self._config,
                        current_position=position,
                    )

                    if result.success:
                        self._logger.info(
                            f"交易指令执行成功: {instruction.op.value}, "
                            f"订单ID: {result.order_id}"
                        )

                        # 检查是否是平仓指令
                        if instruction.op.value == "close_position":
                            has_close_position = True
                    else:
                        self._logger.error(
                            f"交易指令执行失败: {instruction.op.value}, "
                            f"错误: {result.error_message}"
                        )

                except Exception as e:
                    self._logger.error(f"执行交易指令异常: {e}")
                    continue

            # 11. 处理平仓后操作
            if has_close_position:
                await self._handle_position_closed(balance)

            self._logger.info(f"分析流程完成: {self._config.inst_id}")

        except Exception as e:
            self._logger.error(f"分析流程异常: {e}")

    async def _fetch_historical_klines(self) -> list[KlineData] | None:
        """获取历史K线数据

        Returns:
            K线数据列表，失败返回None
        """
        try:
            response = await self._rest_client.get_candles(
                inst_id=self._config.inst_id,
                timeframe=self._config.timeframe,
                limit=self._kline_count,
            )

            if response.get("code") != "0":
                self._logger.error(f"获取K线数据失败: {response.get('msg')}")
                return None

            data = response.get("data", [])
            if not data:
                return None

            klines = []
            for item in data:
                # OKX返回数据格式: [timestamp, open, high, low, close, vol, volCcy]
                klines.append(
                    KlineData(
                        timestamp=item[0],
                        open=float(item[1]),
                        high=float(item[2]),
                        low=float(item[3]),
                        close=float(item[4]),
                    )
                )

            # 按时间顺序排序（从早到晚）
            klines.reverse()
            return klines

        except Exception as e:
            self._logger.error(f"获取历史K线数据异常: {e}")
            return None

    async def _generate_kline_image(
        self,
        klines: list[KlineData],
        ema_values: list[float],
    ) -> str | None:
        """生成K线图并转为base64

        Args:
            klines: K线数据列表
            ema_values: EMA值列表

        Returns:
            base64编码的图片数据，失败返回None
        """
        try:
            import base64

            png_data = self._plotter.plot(
                klines=klines,
                ema_values=ema_values,
                inst_id=self._config.inst_id,
                timeframe=self._config.timeframe,
            )

            return base64.b64encode(png_data).decode("utf-8")

        except Exception as e:
            self._logger.error(f"生成K线图异常: {e}")
            return None

    async def _handle_position_closed(self, balance: Decimal) -> None:
        """处理平仓后操作

        Args:
            balance: 平仓后账户余额
        """
        self._logger.info(f"处理平仓后操作: {self._config.inst_id}")

        # 清空分析历史
        self._history_service.clear_history(self._config.inst_id)

        # 交易记录已在trading_service中写入CSV
        self._logger.info(f"平仓处理完成: {self._config.inst_id}")


class MainEventLoop:
    """主事件循环

    管理所有交易对的运行，处理系统信号，实现优雅关闭。
    """

    def __init__(self, config: ConfigContainer) -> None:
        """初始化主事件循环

        Args:
            config: 配置容器
        """
        self._config = config
        self._logger = Logger()

        # 客户端
        self._okx_rest_client: OkxRestClient | None = None
        self._okx_ws_client: OkxWebSocketClient | None = None
        self._llm_client: LLMClient | None = None

        # 服务
        self._agent_service: AgentService | None = None
        self._history_service: HistoryService | None = None
        self._trading_service: TradingService | None = None

        # 交易对运行器
        self._runners: list[TradingPairRunner] = []

        # 关闭标志
        self._shutdown_event = asyncio.Event()

    async def initialize(self) -> None:
        """初始化所有组件"""
        self._logger.info("初始化主事件循环...")

        demo_mode = self._config.app_config.global_config.demo_mode
        credentials = (
            self._config.okx_demo
            if demo_mode
            else self._config.okx_real
        )

        # 初始化OKX客户端
        self._okx_rest_client = OkxRestClient(
            credentials=credentials,
            is_simulated=demo_mode,
        )
        self._okx_ws_client = OkxWebSocketClient(
            credentials=credentials,
            is_simulated=demo_mode,
        )

        # 初始化LLM客户端
        self._llm_client = LLMClient(
            api_key=self._config.openai_api_key,
            base_url=self._config.openai_base_url or None,
        )

        # 初始化服务
        self._agent_service = AgentService(
            llm_client=self._llm_client,
            prompt_config=self._config.prompt_config,
            llm_model=self._config.app_config.global_config.llm_model,
        )

        self._history_service = HistoryService(
            max_history_length=self._config.app_config.global_config.max_analysis_history_length,
        )

        csv_storage = CSVStorage(
            filepath=self._config.app_config.global_config.trade_record_path,
        )

        self._trading_service = TradingService(
            okx_client=self._okx_rest_client,
            csv_storage=csv_storage,
            trade_pairs_config=self._config.app_config.trade_pairs,
            td_mode=self._config.app_config.global_config.td_mode,
        )

        # 初始化交易服务（设置持仓模式、杠杆等）
        await self._trading_service.initialize()

        # 创建交易对运行器
        for trade_pair in self._config.app_config.trade_pairs:
            runner = TradingPairRunner(
                trade_pair_config=trade_pair,
                okx_rest_client=self._okx_rest_client,
                okx_ws_client=self._okx_ws_client,
                agent_service=self._agent_service,
                history_service=self._history_service,
                trading_service=self._trading_service,
                kline_count=self._config.app_config.global_config.k_line_count,
                risk_per_trade=Decimal("0.01"),  # 默认1%风险
            )
            self._runners.append(runner)

        self._logger.info(f"主事件循环初始化完成，共{len(self._runners)}个交易对")

    async def run(self) -> None:
        """运行主事件循环"""
        self._logger.info("=" * 50)
        self._logger.info("主事件循环启动")
        self._logger.info("=" * 50)

        # 设置信号处理器
        self._setup_signal_handlers()

        # 启动所有交易对运行器
        runner_tasks = []
        for runner in self._runners:
            task = asyncio.create_task(runner.start())
            runner_tasks.append(task)

        # 等待关闭信号
        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            self._logger.info("主事件循环被取消")

        self._logger.info("开始优雅关闭...")

        # 取消所有运行器任务
        for task in runner_tasks:
            if not task.done():
                task.cancel()

        # 等待所有任务完成
        if runner_tasks:
            await asyncio.gather(*runner_tasks, return_exceptions=True)

        self._logger.info("主事件循环已停止")

    def _setup_signal_handlers(self) -> None:
        """设置系统信号处理器"""
        try:
            loop = asyncio.get_event_loop()

            # 处理SIGINT (Ctrl+C)
            loop.add_signal_handler(
                signal.SIGINT,
                lambda: asyncio.create_task(self._handle_shutdown_signal("SIGINT")),
            )

            # 处理SIGTERM
            loop.add_signal_handler(
                signal.SIGTERM,
                lambda: asyncio.create_task(self._handle_shutdown_signal("SIGTERM")),
            )

            self._logger.info("信号处理器已设置")

        except NotImplementedError:
            # Windows可能不支持某些信号
            self._logger.warning("当前平台不支持信号处理器")

    async def _handle_shutdown_signal(self, signal_name: str) -> None:
        """处理关闭信号

        Args:
            signal_name: 信号名称
        """
        self._logger.info(f"收到{signal_name}信号，开始优雅关闭...")
        self._shutdown_event.set()

    async def shutdown(self) -> None:
        """执行关闭操作"""
        self._logger.info("执行关闭操作...")

        # 触发关闭事件
        self._shutdown_event.set()

        # 关闭OKX WebSocket连接
        if self._okx_ws_client:
            await self._okx_ws_client.close()

        # 关闭OKX REST连接
        if self._okx_rest_client:
            await self._okx_rest_client.close()

        self._logger.info("关闭操作完成")
