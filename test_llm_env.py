"""测试LLM环境变量加载和API调用。"""

import asyncio
import os
from dotenv import load_dotenv

from src.infrastructure.llm_client import LLMClient
from src.infrastructure.logger import Logger


async def test_llm():
    """测试LLM客户端。"""
    # 加载.env文件
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
        timeout=30.0,
        max_retries=1,
    )
    
    try:
        print("\n测试1: 文本请求...")
        response = await client.chat(
            model=model,
            system_prompt="你是一个简洁的助手，只回复OK。",
            user_message="回复OK",
            temperature=0.0,
        )
        print(f"文本响应: {response}")
        
        print("\n测试2: 带temperature的文本请求...")
        response2 = await client.chat(
            model=model,
            system_prompt="你是一个助手。",
            user_message="用一句话描述Python",
            temperature=0.0,
        )
        print(f"文本响应2: {response2}")
        
        print("\n所有测试通过!")
        
    except Exception as e:
        print(f"测试失败: {e}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(test_llm())
