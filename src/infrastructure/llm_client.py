"""
LLM客户端封装
基于OpenAI官方异步Python SDK实现
"""

import asyncio
from typing import Optional

from openai import AsyncOpenAI


class LLMClient:
    """LLM客户端"""

    TIMEOUT = 30
    MAX_RETRIES = 1

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "gpt-4o",
    ):
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=self.TIMEOUT,
        )
        self.model = model

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.0,
        images: Optional[list] = None,
    ) -> str:
        """
        发送聊天请求

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息
            temperature: 温度参数，默认0保证确定性
            images: 图片列表，每个元素是base64编码的图片字符串

        Returns:
            LLM的回复文本
        """
        messages = [
            {"role": "system", "content": system_prompt},
        ]

        # 构建用户消息内容
        user_content = []

        if images:
            for img_base64 in images:
                user_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_base64}"
                    }
                })

        user_content.append({
            "type": "text",
            "text": user_message,
        })

        messages.append({"role": "user", "content": user_content})

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                )

                if response and response.choices and len(response.choices) > 0:
                    content = response.choices[0].message.content
                    return content if content else ""
                else:
                    raise LLMError(f"Invalid response format: {response}")

            except Exception as e:
                if attempt == self.MAX_RETRIES:
                    raise LLMError(f"LLM request failed after {self.MAX_RETRIES + 1} attempts: {e}")

                await asyncio.sleep(1)

        return ""

    async def chat_text_only(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.0,
    ) -> str:
        """
        发送纯文本聊天请求（无图片）

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息
            temperature: 温度参数

        Returns:
            LLM的回复文本
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                )

                if response and response.choices and len(response.choices) > 0:
                    content = response.choices[0].message.content
                    return content if content else ""
                else:
                    raise LLMError(f"Invalid response format: {response}")

            except Exception as e:
                if attempt == self.MAX_RETRIES:
                    raise LLMError(f"LLM request failed after {self.MAX_RETRIES + 1} attempts: {e}")

                await asyncio.sleep(1)

        return ""

    async def test_connection(self) -> bool:
        """测试LLM连接"""
        try:
            response = await self.chat_text_only(
                system_prompt="You are a helpful assistant.",
                user_message="Reply with exactly: OK",
            )
            return "OK" in response
        except Exception as e:
            print(f"LLM connection test failed: {e}")
            return False

    async def test_vision(self) -> bool:
        """测试LLM图片解析能力"""
        try:
            # 创建一个简单的1x1像素的PNG图片
            import base64
            # 最简单的PNG图片 (1x1 白色像素)
            png_data = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
            )
            img_base64 = base64.b64encode(png_data).decode("utf-8")

            response = await self.chat(
                system_prompt="You are a helpful assistant.",
                user_message="Describe this image in one word.",
                images=[img_base64],
            )
            return len(response) > 0
        except Exception as e:
            print(f"Vision test failed: {e}")
            return False


class LLMError(Exception):
    """LLM错误"""
    pass
