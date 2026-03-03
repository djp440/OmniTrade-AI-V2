"""主程序入口

负责启动自检、初始化主事件循环、处理命令行参数等。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.application.main_loop import MainEventLoop
from src.application.startup_check import StartupCheckError, StartupChecker, handle_startup_error
from src.infrastructure.logger import Logger


async def main() -> int:
    """主函数

    Returns:
        退出码，0表示成功
    """
    logger = Logger()

    try:
        # 1. 执行启动自检
        checker = StartupChecker()
        config = await checker.run_all_checks()

        # 2. 初始化主事件循环
        main_loop = MainEventLoop(config)
        await main_loop.initialize()

        # 3. 运行主事件循环
        await main_loop.run()

        return 0

    except StartupCheckError as e:
        handle_startup_error(e)
        return e.exit_code

    except KeyboardInterrupt:
        logger.info("收到键盘中断，程序退出")
        return 0

    except Exception as e:
        logger.error(f"程序异常: {e}")
        return 1


def run() -> None:
    """同步入口函数"""
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except Exception as e:
        print(f"程序启动失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
