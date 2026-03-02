"""OKX REST客户端单元测试。"""

import json
from unittest import IsolatedAsyncioTestCase
from unittest import mock

import pytest

from src.infrastructure.okx_auth import OkxCredentials
from src.infrastructure.okx_rest_client import OkxApiError, OkxRestClient


class AsyncContextManagerMock:
    """异步上下文管理器Mock。"""

    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


class TestOkxRestClient(IsolatedAsyncioTestCase):
    """OkxRestClient测试类。"""

    def setUp(self) -> None:
        """设置测试数据。"""
        self.credentials = OkxCredentials(
            api_key="test_api_key",
            api_secret="test_api_secret",
            passphrase="test_passphrase",
        )
        self.client = OkxRestClient(self.credentials, is_simulated=False)

    async def asyncTearDown(self) -> None:
        """异步清理。"""
        await self.client.close()

    def test_init(self) -> None:
        """测试客户端初始化。"""
        self.assertEqual(self.client._credentials, self.credentials)
        self.assertFalse(self.client._is_simulated)
        self.assertIsNone(self.client._session)

    def test_init_simulated(self) -> None:
        """测试模拟盘客户端初始化。"""
        demo_client = OkxRestClient(self.credentials, is_simulated=True)
        self.assertTrue(demo_client._is_simulated)

    async def test_generate_timestamp_format(self) -> None:
        """测试时间戳格式。"""
        timestamp = self.client._generate_timestamp()

        self.assertRegex(
            timestamp,
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
        )

    async def test_request_with_retry_success(self) -> None:
        """测试请求成功。"""
        mock_response = mock.AsyncMock()
        mock_response.status = 200
        mock_response.text = mock.AsyncMock(return_value=json.dumps({"code": "0", "data": []}))

        mock_session = mock.AsyncMock()
        mock_session.closed = False
        mock_session.request = mock.MagicMock(return_value=AsyncContextManagerMock(mock_response))

        self.client._session = mock_session

        result = await self.client._request_with_retry("GET", "/api/v5/account/balance")

        self.assertEqual(result["code"], "0")

    async def test_request_with_retry_api_error(self) -> None:
        """测试API错误响应。"""
        mock_response = mock.AsyncMock()
        mock_response.status = 200
        mock_response.text = mock.AsyncMock(return_value=json.dumps({
            "code": "50001",
            "msg": "API key invalid"
        }))

        mock_session = mock.AsyncMock()
        mock_session.closed = False
        mock_session.request = mock.MagicMock(return_value=AsyncContextManagerMock(mock_response))

        self.client._session = mock_session

        with pytest.raises(OkxApiError) as exc_info:
            await self.client._request_with_retry("GET", "/api/v5/account/balance")

        self.assertEqual(exc_info.value.status_code, 50001)

    async def test_request_with_retry_http_error(self) -> None:
        """测试HTTP错误响应。"""
        mock_response = mock.AsyncMock()
        mock_response.status = 401
        mock_response.text = mock.AsyncMock(return_value="Unauthorized")

        mock_session = mock.AsyncMock()
        mock_session.closed = False
        mock_session.request = mock.MagicMock(return_value=AsyncContextManagerMock(mock_response))

        self.client._session = mock_session

        with pytest.raises(OkxApiError) as exc_info:
            await self.client._request_with_retry("GET", "/api/v5/account/balance")

        self.assertEqual(exc_info.value.status_code, 401)

    def test_okx_api_error(self) -> None:
        """测试API错误异常。"""
        error = OkxApiError("Test error", status_code=500, response={"msg": "error"})

        self.assertEqual(str(error), "Test error")
        self.assertEqual(error.status_code, 500)
        self.assertEqual(error.response, {"msg": "error"})

    def test_okx_api_error_without_optional(self) -> None:
        """测试不带可选参数的API错误异常。"""
        error = OkxApiError("Simple error")

        self.assertEqual(str(error), "Simple error")
        self.assertIsNone(error.status_code)
        self.assertEqual(error.response, {})


class TestOkxRestClientHeaders(IsolatedAsyncioTestCase):
    """OkxRestClient请求头测试类。"""

    def setUp(self) -> None:
        """设置测试数据。"""
        self.credentials = OkxCredentials(
            api_key="test_api_key",
            api_secret="test_api_secret",
            passphrase="test_passphrase",
        )

    async def test_headers_contain_required_fields(self) -> None:
        """测试请求头包含必需字段。"""
        client = OkxRestClient(self.credentials, is_simulated=False)

        mock_response = mock.AsyncMock()
        mock_response.status = 200
        mock_response.text = mock.AsyncMock(return_value=json.dumps({"code": "0", "data": []}))

        mock_session = mock.AsyncMock()
        mock_session.closed = False
        mock_session.request = mock.MagicMock(return_value=AsyncContextManagerMock(mock_response))

        client._session = mock_session

        await client.get_balance()

        call_args = mock_session.request.call_args
        headers = call_args[1]["headers"]

        self.assertIn("OK-ACCESS-KEY", headers)
        self.assertIn("OK-ACCESS-SIGN", headers)
        self.assertIn("OK-ACCESS-TIMESTAMP", headers)
        self.assertIn("OK-ACCESS-PASSPHRASE", headers)
        self.assertIn("Content-Type", headers)

        self.assertEqual(headers["OK-ACCESS-KEY"], self.credentials.api_key)
        self.assertEqual(headers["OK-ACCESS-PASSPHRASE"], self.credentials.passphrase)
        self.assertEqual(headers["Content-Type"], "application/json")

        await client.close()

    async def test_simulated_trading_header(self) -> None:
        """测试模拟盘请求头包含x-simulated-trading。"""
        client = OkxRestClient(self.credentials, is_simulated=True)

        mock_response = mock.AsyncMock()
        mock_response.status = 200
        mock_response.text = mock.AsyncMock(return_value=json.dumps({"code": "0", "data": []}))

        mock_session = mock.AsyncMock()
        mock_session.closed = False
        mock_session.request = mock.MagicMock(return_value=AsyncContextManagerMock(mock_response))

        client._session = mock_session

        await client.get_balance()

        call_args = mock_session.request.call_args
        headers = call_args[1]["headers"]

        self.assertIn("x-simulated-trading", headers)
        self.assertEqual(headers["x-simulated-trading"], "1")

        await client.close()

    async def test_real_trading_no_simulated_header(self) -> None:
        """测试实盘请求头不包含x-simulated-trading。"""
        client = OkxRestClient(self.credentials, is_simulated=False)

        mock_response = mock.AsyncMock()
        mock_response.status = 200
        mock_response.text = mock.AsyncMock(return_value=json.dumps({"code": "0", "data": []}))

        mock_session = mock.AsyncMock()
        mock_session.closed = False
        mock_session.request = mock.MagicMock(return_value=AsyncContextManagerMock(mock_response))

        client._session = mock_session

        await client.get_balance()

        call_args = mock_session.request.call_args
        headers = call_args[1]["headers"]

        self.assertNotIn("x-simulated-trading", headers)

        await client.close()
