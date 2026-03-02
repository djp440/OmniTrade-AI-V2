"""LLM客户端集成测试。

注意：运行这些测试需要有效的OpenAI API密钥。
设置环境变量 OPENAI_API_KEY 来运行测试。
"""

import os
import unittest
from datetime import datetime, timedelta

import numpy as np

from src.infrastructure.llm_client import LLMClient, LLMError
from src.infrastructure.kline_plotter import KlinePlotter, KlineData
from src.infrastructure.logger import Logger


@unittest.skipUnless(
    os.environ.get("OPENAI_API_KEY"),
    "需要设置 OPENAI_API_KEY 环境变量"
)
class TestLLMIntegration(unittest.IsolatedAsyncioTestCase):
    """LLM客户端集成测试类。"""

    async def asyncSetUp(self):
        """异步测试前置。"""
        self.logger = Logger()
        self.logger.initialize(log_dir="./logs", log_level="DEBUG")

        api_key = os.environ.get("OPENAI_API_KEY")
        base_url = os.environ.get("OPENAI_BASE_URL")

        self.client = LLMClient(
            api_key=api_key,
            base_url=base_url,
            timeout=30.0,
            max_retries=1,
        )

        self.model = os.environ.get("TEST_LLM_MODEL", "gpt-4o-mini")

    async def asyncTearDown(self):
        """异步测试后置。"""
        await self.client.close()

    async def test_text_request_success(self):
        """测试文本请求成功。"""
        response = await self.client.chat(
            model=self.model,
            system_prompt="你是一个简洁的助手，只回复OK。",
            user_message="回复OK",
            temperature=0.0,
        )

        self.assertIsInstance(response, str)
        self.assertIn("OK", response.upper())

    async def test_text_request_with_temperature(self):
        """测试不同temperature的文本请求。"""
        response = await self.client.chat(
            model=self.model,
            system_prompt="你是一个助手。",
            user_message="用一句话描述Python",
            temperature=0.0,
        )

        self.assertIsInstance(response, str)
        self.assertGreater(len(response), 0)

    async def test_image_request_success(self):
        """测试图片请求成功。"""
        plotter = KlinePlotter()

        klines = self._generate_sample_klines(20)
        png_data = plotter.plot(klines)

        response = await self.client.chat(
            model=self.model,
            system_prompt="你是一个技术分析专家。请简要描述这张K线图的趋势。",
            user_message="分析这张K线图的趋势",
            image_data=png_data,
            temperature=0.0,
        )

        self.assertIsInstance(response, str)
        self.assertGreater(len(response), 0)

    async def test_image_with_ema_request(self):
        """测试带EMA均线的图片请求。"""
        plotter = KlinePlotter()

        klines = self._generate_sample_klines(30)
        closes = np.array([k.close for k in klines])

        alpha = 2.0 / 21.0
        ema = np.zeros_like(closes)
        ema[:19] = np.nan
        ema[19] = np.mean(closes[:20])
        for i in range(20, len(closes)):
            ema[i] = alpha * closes[i] + (1 - alpha) * ema[i - 1]

        png_data = plotter.plot(klines, ema)

        response = await self.client.chat(
            model=self.model,
            system_prompt="你是一个技术分析专家。请描述这张K线图的趋势和EMA均线的位置关系。",
            user_message="分析K线趋势和EMA20均线",
            image_data=png_data,
            temperature=0.0,
        )

        self.assertIsInstance(response, str)
        self.assertGreater(len(response), 0)

    async def test_invalid_api_key_raises_error(self):
        """测试无效API密钥抛出错误。"""
        invalid_client = LLMClient(
            api_key="invalid-key",
            timeout=5.0,
            max_retries=0,
        )

        with self.assertRaises(LLMError):
            await invalid_client.chat(
                model=self.model,
                system_prompt="测试",
                user_message="测试",
            )

        await invalid_client.close()

    def _generate_sample_klines(self, count: int) -> list[KlineData]:
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


class TestLLMClientMock(unittest.IsolatedAsyncioTestCase):
    """LLM客户端模拟测试类（不需要API密钥）。"""

    async def test_client_initialization(self):
        """测试客户端初始化。"""
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.test.com/v1",
            timeout=30.0,
            max_retries=1,
        )

        self.assertEqual(client._timeout, 30.0)
        self.assertEqual(client._max_retries, 1)

        await client.close()


if __name__ == "__main__":
    unittest.main()
