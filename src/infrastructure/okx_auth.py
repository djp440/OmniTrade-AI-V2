"""OKX API认证模块，实现HMAC-SHA256签名算法。"""

from __future__ import annotations

import base64
import hmac
import hashlib
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class OkxCredentials:
    """OKX API凭证。"""

    api_key: str
    api_secret: str
    passphrase: str


class OkxSigner:
    """OKX API签名生成器。

    按照OKX官方文档实现HMAC-SHA256签名算法。
    签名内容格式：timestamp + method + requestPath + body
    """

    def __init__(self, credentials: OkxCredentials) -> None:
        """初始化签名器。

        Args:
            credentials: OKX API凭证
        """
        self._credentials = credentials

    def generate_signature(
        self,
        timestamp: str,
        method: Literal["GET", "POST", "PUT", "DELETE"],
        request_path: str,
        body: str = "",
    ) -> str:
        """生成HMAC-SHA256签名。

        Args:
            timestamp: ISO格式的时间戳，如 "2024-01-01T00:00:00.000Z"
            method: HTTP方法
            request_path: 请求路径，如 "/api/v5/account/balance"
            body: 请求体JSON字符串，GET请求为空字符串

        Returns:
            Base64编码的签名

        Raises:
            ValueError: 参数无效时抛出
        """
        if not timestamp:
            raise ValueError("timestamp不能为空")
        if not method:
            raise ValueError("method不能为空")
        if not request_path:
            raise ValueError("request_path不能为空")

        message = timestamp + method.upper() + request_path + body

        signature = hmac.new(
            key=self._credentials.api_secret.encode("utf-8"),
            msg=message.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()

        return base64.b64encode(signature).decode("utf-8")

    def generate_headers(
        self,
        timestamp: str,
        method: Literal["GET", "POST", "PUT", "DELETE"],
        request_path: str,
        body: str = "",
        is_simulated: bool = False,
    ) -> dict[str, str]:
        """生成完整的请求头。

        Args:
            timestamp: ISO格式的时间戳
            method: HTTP方法
            request_path: 请求路径
            body: 请求体JSON字符串
            is_simulated: 是否使用模拟盘

        Returns:
            包含所有必要请求头的字典
        """
        signature = self.generate_signature(timestamp, method, request_path, body)

        headers = {
            "OK-ACCESS-KEY": self._credentials.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self._credentials.passphrase,
            "Content-Type": "application/json",
        }

        if is_simulated:
            headers["x-simulated-trading"] = "1"

        return headers
