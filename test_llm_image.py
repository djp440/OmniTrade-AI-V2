"""测试LLM图片解析功能。"""

import asyncio
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

import numpy as np

from src.infrastructure.llm_client import LLMClient
from src.infrastructure.kline_plotter import KlinePlotter, KlineData
from src.infrastructure.ema_calculator import EMACalculator
from src.infrastructure.logger import Logger


def generate_sample_klines(count: int) -> list[KlineData]:
    """生成示例K线数据。"""
    klines = []
    base_price = 50000.0
    base_time = datetime(2024, 1, 1, 0, 0, 0)
    
    for i in range(count):
        open_price = base_price + i * 100 + np.random.randn() * 50
        close_price = open_price + np.random.randn() * 200
        high_price = max(open_price, close_price) + abs(np.random.randn()) * 100
        low_price = min(open_price, close_price) - abs(np.random.randn()) * 100
        
        klines.append(KlineData(
            timestamp=base_time + timedelta(hours=i),
            open=round(open_price, 2),
            high=round(high_price, 2),
            low=round(low_price, 2),
            close=round(close_price, 2),
        ))
    
    return klines


async def test_llm_image():
    """测试LLM图片解析。"""
    load_dotenv('config/.env')
    
    logger = Logger()
    logger.initialize(log_dir="./logs", log_level="DEBUG")
    
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL")
    model = os.environ.get("TEST_LLM_MODEL", "gpt-4o-mini")
    
    print(f"API Key exists: {bool(api_key)}")
    print(f"Base URL: {base_url}")
    print(f"Model: {model}")
    
    if not api_key:
        print("错误: 未找到 OPENAI_API_KEY 环境变量")
        return
    
    client = LLMClient(
        api_key=api_key,
        base_url=base_url,
        timeout=60.0,
        max_retries=1,
    )
    
    try:
        print("\n生成K线图...")
        plotter = KlinePlotter()
        klines = generate_sample_klines(30)
        
        # 计算EMA
        closes = np.array([k.close for k in klines])
        ema = EMACalculator.calculate_ema20(closes)
        
        png_data = plotter.plot(klines, ema)
        print(f"K线图生成完成: {len(png_data)} bytes")
        
        # 保存一份用于调试
        debug_path = "logs/test_kline_image.png"
        plotter.save_to_file(debug_path, klines, ema)
        
        print("\n测试: 图片分析请求...")
        response = await client.chat(
            model=model,
            system_prompt="你是一个专业的加密货币技术分析专家。请简要描述这张K线图的趋势和EMA均线的位置关系。",
            user_message="分析这张K线图的趋势",
            image_data=png_data,
            temperature=0.0,
        )
        print(f"图片分析响应: {response}")
        
        print("\n所有图片测试通过!")
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(test_llm_image())
