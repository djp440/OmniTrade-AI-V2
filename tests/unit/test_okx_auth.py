"""OKX认证模块单元测试。"""

import base64
import hmac
import hashlib
from unittest import TestCase

import pytest

from src.infrastructure.okx_auth import OkxCredentials, OkxSigner


class TestOkxSigner(TestCase):
    """OkxSigner测试类。"""

    def setUp(self) -> None:
        """设置测试数据。"""
        self.credentials = OkxCredentials(
            api_key="test_api_key",
            api_secret="test_api_secret",
            passphrase="test_passphrase",
        )
        self.signer = OkxSigner(self.credentials)

    def test_generate_signature_get_request(self) -> None:
        """测试GET请求签名生成。"""
        timestamp = "2024-01-15T10:30:00.000Z"
        method = "GET"
        request_path = "/api/v5/account/balance"
        body = ""

        signature = self.signer.generate_signature(timestamp, method, request_path, body)

        expected_message = timestamp + method + request_path + body
        expected_signature = base64.b64encode(
            hmac.new(
                key=self.credentials.api_secret.encode("utf-8"),
                msg=expected_message.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
        ).decode("utf-8")

        self.assertEqual(signature, expected_signature)

    def test_generate_signature_post_request(self) -> None:
        """测试POST请求签名生成。"""
        timestamp = "2024-01-15T10:30:00.000Z"
        method = "POST"
        request_path = "/api/v5/trade/order"
        body = '{"instId":"BTC-USDT-SWAP","tdMode":"cross","side":"buy","ordType":"market","sz":"1"}'

        signature = self.signer.generate_signature(timestamp, method, request_path, body)

        expected_message = timestamp + method + request_path + body
        expected_signature = base64.b64encode(
            hmac.new(
                key=self.credentials.api_secret.encode("utf-8"),
                msg=expected_message.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
        ).decode("utf-8")

        self.assertEqual(signature, expected_signature)

    def test_generate_signature_with_different_methods(self) -> None:
        """测试不同HTTP方法的签名。"""
        timestamp = "2024-01-15T10:30:00.000Z"
        request_path = "/api/v5/account/balance"
        body = ""

        methods = ["GET", "POST", "PUT", "DELETE"]
        signatures = {}

        for method in methods:
            signature = self.signer.generate_signature(timestamp, method, request_path, body)
            signatures[method] = signature

        for method in methods:
            expected_message = timestamp + method + request_path + body
            expected_signature = base64.b64encode(
                hmac.new(
                    key=self.credentials.api_secret.encode("utf-8"),
                    msg=expected_message.encode("utf-8"),
                    digestmod=hashlib.sha256,
                ).digest()
            ).decode("utf-8")
            self.assertEqual(signatures[method], expected_signature)

    def test_generate_signature_empty_body(self) -> None:
        """测试空请求体的签名。"""
        timestamp = "2024-01-15T10:30:00.000Z"
        method = "GET"
        request_path = "/api/v5/account/balance"

        signature_with_empty = self.signer.generate_signature(timestamp, method, request_path, "")
        signature_without_body = self.signer.generate_signature(timestamp, method, request_path)

        self.assertEqual(signature_with_empty, signature_without_body)

    def test_generate_signature_invalid_params(self) -> None:
        """测试无效参数抛出异常。"""
        with pytest.raises(ValueError, match="timestamp不能为空"):
            self.signer.generate_signature("", "GET", "/api/v5/account/balance")

        with pytest.raises(ValueError, match="method不能为空"):
            self.signer.generate_signature("2024-01-15T10:30:00.000Z", "", "/api/v5/account/balance")

        with pytest.raises(ValueError, match="request_path不能为空"):
            self.signer.generate_signature("2024-01-15T10:30:00.000Z", "GET", "")

    def test_generate_headers_real_trading(self) -> None:
        """测试实盘交易请求头生成。"""
        timestamp = "2024-01-15T10:30:00.000Z"
        method = "GET"
        request_path = "/api/v5/account/balance"

        headers = self.signer.generate_headers(timestamp, method, request_path, is_simulated=False)

        self.assertEqual(headers["OK-ACCESS-KEY"], self.credentials.api_key)
        self.assertEqual(headers["OK-ACCESS-TIMESTAMP"], timestamp)
        self.assertEqual(headers["OK-ACCESS-PASSPHRASE"], self.credentials.passphrase)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertNotIn("x-simulated-trading", headers)

        expected_signature = self.signer.generate_signature(timestamp, method, request_path, "")
        self.assertEqual(headers["OK-ACCESS-SIGN"], expected_signature)

    def test_generate_headers_simulated_trading(self) -> None:
        """测试模拟盘交易请求头生成。"""
        timestamp = "2024-01-15T10:30:00.000Z"
        method = "GET"
        request_path = "/api/v5/account/balance"

        headers = self.signer.generate_headers(timestamp, method, request_path, is_simulated=True)

        self.assertEqual(headers["OK-ACCESS-KEY"], self.credentials.api_key)
        self.assertEqual(headers["OK-ACCESS-TIMESTAMP"], timestamp)
        self.assertEqual(headers["OK-ACCESS-PASSPHRASE"], self.credentials.passphrase)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["x-simulated-trading"], "1")

    def test_generate_headers_with_body(self) -> None:
        """测试带请求体的请求头生成。"""
        timestamp = "2024-01-15T10:30:00.000Z"
        method = "POST"
        request_path = "/api/v5/trade/order"
        body = '{"instId":"BTC-USDT-SWAP","sz":"1"}'

        headers = self.signer.generate_headers(timestamp, method, request_path, body)

        expected_signature = self.signer.generate_signature(timestamp, method, request_path, body)
        self.assertEqual(headers["OK-ACCESS-SIGN"], expected_signature)

    def test_signature_consistency(self) -> None:
        """测试相同输入产生相同签名（幂等性）。"""
        timestamp = "2024-01-15T10:30:00.000Z"
        method = "GET"
        request_path = "/api/v5/account/balance"

        signature1 = self.signer.generate_signature(timestamp, method, request_path)
        signature2 = self.signer.generate_signature(timestamp, method, request_path)
        signature3 = self.signer.generate_signature(timestamp, method, request_path)

        self.assertEqual(signature1, signature2)
        self.assertEqual(signature2, signature3)

    def test_signature_different_credentials(self) -> None:
        """测试不同凭证产生不同签名。"""
        timestamp = "2024-01-15T10:30:00.000Z"
        method = "GET"
        request_path = "/api/v5/account/balance"

        signature1 = self.signer.generate_signature(timestamp, method, request_path)

        different_credentials = OkxCredentials(
            api_key="different_key",
            api_secret="different_secret",
            passphrase="different_passphrase",
        )
        different_signer = OkxSigner(different_credentials)
        signature2 = different_signer.generate_signature(timestamp, method, request_path)

        self.assertNotEqual(signature1, signature2)
