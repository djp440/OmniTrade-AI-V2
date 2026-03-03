"""LLM客户端，基于OpenAI官方异步SDK实现。"""

from __future__ import annotations

import asyncio
import base64
import io
from typing import Any

from openai import AsyncOpenAI, APIError

from src.infrastructure.logger import Logger


class LLMClient:
    """LLM客户端，支持文本和多模态调用。"""

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 1,
    ) -> None:
        """初始化LLM客户端。

        Args:
            api_key: OpenAI API密钥
            base_url: 自定义API基础URL，用于代理
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
        """
        self._logger = Logger()
        self._timeout = timeout
        self._max_retries = max_retries

        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        self._client = AsyncOpenAI(**client_kwargs)

    async def chat(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        image_data: bytes | None = None,
        temperature: float = 0.0,
    ) -> str:
        """发送聊天请求，支持文本和多模态。

        Args:
            model: 模型名称
            system_prompt: 系统提示词
            user_message: 用户消息
            image_data: 图片数据（PNG格式），用于多模态调用
            temperature: 采样温度，默认0保证确定性

        Returns:
            LLM响应文本

        Raises:
            LLMError: 调用失败且重试后仍失败
        """
        messages = self._build_messages(system_prompt, user_message, image_data)

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                self._logger.debug(
                    f"LLM请求: model={model}, attempt={attempt + 1}, "
                    f"has_image={image_data is not None}"
                )

                response = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                    ),
                    timeout=self._timeout,
                )

                content = response.choices[0].message.content
                if content is None:
                    content = ""

                self._logger.debug(f"LLM响应: {content[:100]}...")
                return content

            except asyncio.TimeoutError:
                last_error = TimeoutError(f"LLM请求超时（{self._timeout}秒）")
                self._logger.warning(f"LLM请求超时，尝试重试 ({attempt + 1}/{self._max_retries + 1})")
            except APIError as e:
                last_error = e
                self._logger.warning(f"LLM API错误: {e}，尝试重试 ({attempt + 1}/{self._max_retries + 1})")
            except Exception as e:
                last_error = e
                self._logger.warning(f"LLM请求异常: {e}，尝试重试 ({attempt + 1}/{self._max_retries + 1})")

            if attempt < self._max_retries:
                await asyncio.sleep(1)

        error_msg = f"LLM调用失败，已重试{self._max_retries}次: {last_error}"
        self._logger.error(error_msg)
        raise LLMError(error_msg) from last_error

    def _build_messages(
        self,
        system_prompt: str,
        user_message: str,
        image_data: bytes | None = None,
    ) -> list[dict[str, Any]]:
        """构建消息列表。

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息
            image_data: 图片数据

        Returns:
            消息列表
        """
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]

        if image_data is not None:
            base64_image = base64.b64encode(image_data).decode("utf-8")
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_message},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}",
                        },
                    },
                ],
            })
        else:
            messages.append({"role": "user", "content": user_message})

        return messages

    async def close(self) -> None:
        """关闭客户端连接。"""
        await self._client.close()


class LLMError(Exception):
    """LLM调用错误。"""

    pass
