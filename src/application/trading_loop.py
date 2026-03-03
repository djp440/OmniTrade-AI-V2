"""
主事件循环和单交易对分析流程
"""

import asyncio
import signal
from datetime import datetime

from src.domain.models import (
    AccountBalance,
    AnalystInput,
    KlineCloseEvent,
    Position,
    PositionCloseEvent,
    PositionDirection,
    TradeInstruction,
    TradeOperation,
    TradeRecord,
    TraderInput,
)
from src.infrastructure.config_loader import AppConfig, TradePairConfig
from src.infrastructure.logger import Logger
from src.infrastructure.okx_client import OKXRestClient, OKXWebSocketClient
from src.infrastructure.utils import TradeRecordStorage
from src.services.agent_service import AgentService
from src.services.history_service import HistoryService
from src.services.kline_service import KlineService
from src.services.trade_service import TradeService


class TradingLoop:
    """交易主循环"""

    def __init__(
        self,
        config: AppConfig,
        okx_rest_client: OKXRestClient,
        okx_ws_client: OKXWebSocketClient,
        agent_service: AgentService,
        trade_service: TradeService,
        kline_service: KlineService,
        history_service: HistoryService,
        trade_record_storage: TradeRecordStorage,
        logger: Logger,
    ):
        self.config = config
        self.okx_rest_client = okx_rest_client
        self.okx_ws_client = okx_ws_client
        self.agent_service = agent_service
        self.trade_service = trade_service
        self.kline_service = kline_service
        self.history_service = history_service
        self.trade_record_storage = trade_record_storage
        self.logger = logger

        self.running = False
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: list[asyncio.Task] = []

    async def run(self):
        """运行主事件循环"""
        self.logger.info("Starting trading loop...")
        self.running = True

        # 为每个交易对创建锁
        for pair in self.config.trade_pairs:
            self._locks[pair.inst_id] = asyncio.Lock()

        # 设置信号处理
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                asyncio.get_event_loop().add_signal_handler(
                    sig, lambda: asyncio.create_task(self.stop())
                )
            except NotImplementedError:
                # Windows不支持某些信号
                pass

        # 为每个交易对启动独立的协程
        for pair in self.config.trade_pairs:
            task = asyncio.create_task(
                self._run_trade_pair(pair),
                name=f"trading_pair_{pair.inst_id}",
            )
            self._tasks.append(task)

        # 启动WebSocket监听
        ws_task = asyncio.create_task(self._websocket_listener(), name="websocket_listener")
        self._tasks.append(ws_task)

        # 等待所有任务完成
        try:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        except asyncio.CancelledError:
            self.logger.info("Trading loop cancelled")

    async def _run_trade_pair(self, pair: TradePairConfig):
        """运行单个交易对的循环"""
        self.logger.info(f"Starting trading loop for {pair.inst_id}")

        try:
            # 确保WebSocket已连接
            if not self.okx_ws_client._is_ws_connected():
                self.logger.info(f"Connecting WebSocket for {pair.inst_id}...")
                await self.okx_ws_client.connect()

            # 订阅K线
            await self.kline_service.subscribe_kline(
                inst_id=pair.inst_id,
                timeframe=pair.timeframe,
                callback=lambda event: self._on_kline_close(event, pair),
            )

            # 保持运行
            while self.running:
                await asyncio.sleep(1)

        except Exception as e:
            self.logger.error(f"Error in trading loop for {pair.inst_id}: {e}")

    async def _websocket_listener(self):
        """WebSocket监听协程"""
        try:
            await self.okx_ws_client.listen(lambda data: None)
        except Exception as e:
            self.logger.error(f"WebSocket listener error: {e}")
            if self.running:
                self.logger.fatal("WebSocket connection lost, stopping...")
                await self.stop()

    async def _on_kline_close(self, event: KlineCloseEvent, pair: TradePairConfig):
        """K线收盘事件处理"""
        self.logger.info(
            f"Kline closed for {event.inst_id} at {datetime.fromtimestamp(event.kline.timestamp / 1000)}"
        )

        # 尝试获取锁
        lock = self._locks.get(event.inst_id)
        if lock is None:
            self.logger.error(f"No lock found for {event.inst_id}")
            return

        if lock.locked():
            self.logger.warning(
                f"Previous analysis for {event.inst_id} is still running, skipping..."
            )
            return

        async with lock:
            try:
                await self._analyze_and_trade(event, pair)
            except Exception as e:
                self.logger.error(f"Error during analysis for {event.inst_id}: {e}")

    async def _analyze_and_trade(self, event: KlineCloseEvent, pair: TradePairConfig):
        """分析并执行交易"""
        self.logger.info(f"Starting analysis for {event.inst_id}")

        # 1. 并行查询余额和仓位
        balance_task = self.trade_service.get_balance("USDT")
        position_task = self.trade_service.get_position(event.inst_id)

        balance, position = await asyncio.gather(balance_task, position_task)

        self.logger.info(
            f"Account balance: {balance.available} USDT, "
            f"Position: {position.direction.value if not position.is_empty else 'empty'}"
        )

        # 2. 获取历史K线数据并生成图表
        klines = await self.kline_service.get_historical_klines(
            inst_id=event.inst_id,
            timeframe=pair.timeframe,
            limit=self.config.global_config.k_line_count,
        )

        if len(klines) < 20:
            self.logger.warning(f"Not enough klines for {event.inst_id}: {len(klines)}")
            return

        # 计算EMA20
        ema_values = self.kline_service.calculate_ema(klines, period=20)

        # 生成K线图
        kline_image = self.kline_service.generate_chart(
            klines=klines,
            ema_values=ema_values,
            inst_id=event.inst_id,
            timeframe=pair.timeframe,
        )

        # 3. 获取分析历史
        analysis_history = self.history_service.get_history(event.inst_id)

        # 4. 构建分析师输入
        analyst_input = AnalystInput(
            kline_image_base64=kline_image,
            analysis_history=analysis_history,
            current_position=position,
            account_balance=balance,
            trade_pair_config={
                "inst_id": pair.inst_id,
                "timeframe": pair.timeframe,
                "leverage": pair.leverage,
                "position_size": pair.position_size,
                "stop_loss_ratio": pair.stop_loss_ratio,
                "take_profit_ratio": pair.take_profit_ratio,
            },
            current_time=datetime.now().isoformat(),
        )

        # 5. 构建交易员输入
        current_price = klines[-1].close
        trader_input = TraderInput(
            analyst_output=None,  # 将在调用分析师后填充
            current_position=position,
            account_balance=balance,
            current_price=current_price,
            risk_per_trade=self.config.global_config.risk_per_trade,
            trade_pair_config={
                "inst_id": pair.inst_id,
                "timeframe": pair.timeframe,
                "leverage": pair.leverage,
                "position_size": pair.position_size,
                "stop_loss_ratio": pair.stop_loss_ratio,
                "take_profit_ratio": pair.take_profit_ratio,
            },
        )

        # 6. 调用Agent进行分析
        analyst_output, trader_output, compressor_output = (
            await self.agent_service.analyze_and_trade(analyst_input, trader_input)
        )

        self.logger.info(f"Analysis complete for {event.inst_id}")
        self.logger.info(f"Trader instructions: {len(trader_output.instructions)} commands")

        # 7. 保存压缩后的分析到历史
        self.history_service.add_record(event.inst_id, compressor_output.compressed_text)

        # 8. 执行交易指令
        has_close_position = False
        for instruction in trader_output.instructions:
            try:
                result = await self.trade_service.execute_instruction(
                    inst_id=event.inst_id,
                    instruction=instruction,
                    td_mode=self.config.global_config.td_mode,
                    trade_pair_config=pair,
                )

                if instruction.op == TradeOperation.CLOSE_POSITION:
                    has_close_position = True

            except Exception as e:
                self.logger.error(f"Failed to execute instruction {instruction.op.value}: {e}")

        # 9. 如果执行了平仓，清空历史并保存交易记录
        if has_close_position:
            await self._handle_position_close(event.inst_id, position, balance)

        self.logger.info(f"Analysis and trading complete for {event.inst_id}")

    async def _handle_position_close(
        self, inst_id: str, position: Position, balance: AccountBalance
    ):
        """处理平仓事件"""
        self.logger.info(f"Handling position close for {inst_id}")

        # 清空分析历史
        self.history_service.clear_history(inst_id)

        # 保存交易记录
        trade_record = TradeRecord(
            timestamp=datetime.now().isoformat(),
            inst_id=inst_id,
            position_direction=position.direction.value,
            position_size=position.size,
            entry_avg_price=position.entry_price,
            exit_avg_price=0,  # 需要通过API查询实际平仓价格
            realized_pnl=0,  # 需要通过API查询实际盈亏
            balance_after_close=balance.equity,
            order_id="",
        )

        self.trade_service.save_trade_record(trade_record)

    async def stop(self):
        """优雅停止"""
        self.logger.info("Stopping trading loop...")
        self.running = False

        # 取消所有任务
        for task in self._tasks:
            if not task.done():
                task.cancel()

        # 关闭WebSocket连接
        await self.okx_ws_client.close()

        # 刷新日志
        self.logger.flush()

        self.logger.info("Trading loop stopped")
