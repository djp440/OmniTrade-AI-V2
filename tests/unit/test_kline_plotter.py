"""K线绘图工具单元测试。"""

import base64
import os
import tempfile
import unittest
from datetime import datetime, timedelta

import numpy as np

from src.infrastructure.kline_plotter import KlinePlotter, KlineData


class TestKlinePlotter(unittest.TestCase):
    """K线绘图器测试类。"""

    def setUp(self):
        """测试前置。"""
        self.plotter = KlinePlotter()
        self.klines = self._generate_sample_klines(30)

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

    def test_plot_returns_png_bytes(self):
        """测试plot方法返回PNG字节数据。"""
        png_data = self.plotter.plot(self.klines)

        self.assertIsInstance(png_data, bytes)
        self.assertGreater(len(png_data), 0)

        self.assertEqual(png_data[:8], b'\x89PNG\r\n\x1a\n')

    def test_plot_with_ema(self):
        """测试带EMA的绘图。"""
        closes = np.array([k.close for k in self.klines])

        alpha = 2.0 / 21.0
        ema = np.zeros_like(closes)
        ema[:19] = np.nan
        ema[19] = np.mean(closes[:20])
        for i in range(20, len(closes)):
            ema[i] = alpha * closes[i] + (1 - alpha) * ema[i - 1]

        png_data = self.plotter.plot(self.klines, ema)

        self.assertIsInstance(png_data, bytes)
        self.assertGreater(len(png_data), 0)

    def test_plot_empty_klines_raises_error(self):
        """测试空K线数据抛出异常。"""
        with self.assertRaises(ValueError) as context:
            self.plotter.plot([])

        self.assertIn("不能为空", str(context.exception))

    def test_plot_to_base64(self):
        """测试base64编码输出。"""
        base64_str = self.plotter.plot_to_base64(self.klines)

        self.assertIsInstance(base64_str, str)

        decoded = base64.b64decode(base64_str)
        self.assertEqual(decoded[:8], b'\x89PNG\r\n\x1a\n')

    def test_save_to_file(self):
        """测试保存到文件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test_kline.png")

            self.plotter.save_to_file(filepath, self.klines)

            self.assertTrue(os.path.exists(filepath))
            self.assertGreater(os.path.getsize(filepath), 0)

            with open(filepath, "rb") as f:
                header = f.read(8)
                self.assertEqual(header, b'\x89PNG\r\n\x1a\n')

    def test_plot_resolution(self):
        """测试图片分辨率。"""
        png_data = self.plotter.plot(self.klines)

        self.assertIsInstance(png_data, bytes)
        self.assertGreater(len(png_data), 1000)

    def test_plot_single_kline(self):
        """测试单根K线绘图。"""
        single_kline = [self.klines[0]]

        png_data = self.plotter.plot(single_kline)

        self.assertIsInstance(png_data, bytes)
        self.assertGreater(len(png_data), 0)

    def test_plot_many_klines(self):
        """测试大量K线绘图。"""
        many_klines = self._generate_sample_klines(100)

        png_data = self.plotter.plot(many_klines)

        self.assertIsInstance(png_data, bytes)
        self.assertGreater(len(png_data), 0)


if __name__ == "__main__":
    unittest.main()
