"""
OKX多Agent自动交易机器人 - 主程序入口
"""

import asyncio
import sys
from pathlib import Path

# 添加src目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from src.application.bootstrap import run_bootstrap
from src.application.trading_loop import TradingLoop
from src.infrastructure.config_loader import load_config
from src.infrastructure.llm_client import LLMClient
from src.infrastructure.logger import get_logger
from src.infrastructure.okx_client import OKXRestClient, OKXWebSocketClient
from src.infrastructure.utils import TradeRecordStorage
from src.services.agent_service import AgentService
from src.services.history_service import HistoryService
from src.services.kline_service import KlineService
from src.services.trade_service import TradeService


async def main():
    """主函数"""
    print("=" * 60)
    print("OKX Multi-Agent Auto Trading Bot")
    print("=" * 60)

    # 加载配置
    config = load_config(
        env_path=".env",
        config_path="config/config.toml",
        prompt_path="config/prompt.toml",
    )

    # 初始化日志
    logger = get_logger(
        log_dir=config.global_config.log_dir,
        log_level=config.global_config.log_level,
    )

    logger.info("Application starting...")
    logger.info(f"Demo mode: {config.global_config.demo_mode}")
    logger.info(f"Trade pairs: {[p.inst_id for p in config.trade_pairs]}")

    try:
        # 运行启动自检
        bootstrap = await run_bootstrap(config, logger)

        okx_rest_client = bootstrap.get_okx_client()
        llm_client = bootstrap.get_llm_client()

        # 初始化WebSocket客户端
        okx_ws_client = OKXWebSocketClient(
            demo_mode=config.global_config.demo_mode
        )
        await okx_ws_client.connect()

        # 初始化交易记录存储
        trade_record_storage = TradeRecordStorage(
            config.global_config.trade_record_path
        )

        # 初始化服务
        trade_service = TradeService(
            okx_client=okx_rest_client,
            trade_record_storage=trade_record_storage,
            logger=logger,
        )

        kline_service = KlineService(
            okx_rest_client=okx_rest_client,
            okx_ws_client=okx_ws_client,
            logger=logger,
        )

        agent_service = AgentService(
            llm_client=llm_client,
            prompts=config.prompts,
            logger=logger,
        )

        history_service = HistoryService(
            max_history_length=config.global_config.max_analysis_history_length,
            logger=logger,
        )

        # 初始化持仓模式和杠杆
        await trade_service.initialize_position_mode(
            trade_pairs=config.trade_pairs,
            td_mode=config.global_config.td_mode,
        )

        # 创建并运行交易循环
        trading_loop = TradingLoop(
            config=config,
            okx_rest_client=okx_rest_client,
            okx_ws_client=okx_ws_client,
            agent_service=agent_service,
            trade_service=trade_service,
            kline_service=kline_service,
            history_service=history_service,
            trade_record_storage=trade_record_storage,
            logger=logger,
        )

        await trading_loop.run()

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.fatal(f"Fatal error: {e}")
        raise
    finally:
        # 清理资源
        if 'okx_rest_client' in locals():
            await okx_rest_client.close()
        if 'okx_ws_client' in locals():
            await okx_ws_client.close()
        logger.info("Application shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
