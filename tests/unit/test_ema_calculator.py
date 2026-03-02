"""EMA计算工具单元测试。"""

import unittest

import numpy as np

from src.infrastructure.ema_calculator import EMACalculator


class TestEMACalculator(unittest.TestCase):
    """EMA计算器测试类。"""

    def test_calculate_basic(self):
        """测试基本EMA计算。"""
        closes = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0,
                          110.0, 111.0, 112.0, 113.0, 114.0, 115.0, 116.0, 117.0, 118.0, 119.0,
                          120.0])

        ema = EMACalculator.calculate(closes, period=20)

        self.assertEqual(len(ema), len(closes))

        self.assertTrue(np.isnan(ema[0]))
        self.assertTrue(np.isnan(ema[18]))

        self.assertFalse(np.isnan(ema[19]))
        self.assertFalse(np.isnan(ema[20]))

    def test_calculate_ema20_known_values(self):
        """测试EMA20计算结果与已知值一致。"""
        closes = np.array([10.0] * 20 + [20.0])

        ema = EMACalculator.calculate_ema20(closes)

        sma = np.mean(closes[:20])
        alpha = 2.0 / 21.0
        expected_ema20 = alpha * closes[20] + (1 - alpha) * sma

        self.assertAlmostEqual(ema[20], expected_ema20, places=10)

    def test_calculate_with_list_input(self):
        """测试列表输入。"""
        closes = [100.0] * 25

        ema = EMACalculator.calculate(closes, period=20)

        self.assertEqual(len(ema), 25)
        self.assertTrue(np.isnan(ema[0]))
        self.assertFalse(np.isnan(ema[20]))

    def test_calculate_insufficient_data(self):
        """测试数据不足时抛出异常。"""
        closes = np.array([100.0] * 10)

        with self.assertRaises(ValueError) as context:
            EMACalculator.calculate(closes, period=20)

        self.assertIn("数据点不足", str(context.exception))

    def test_calculate_invalid_period(self):
        """测试无效周期。"""
        closes = np.array([100.0] * 25)

        with self.assertRaises(ValueError) as context:
            EMACalculator.calculate(closes, period=0)

        self.assertIn("周期必须大于0", str(context.exception))

    def test_calculate_wrong_dimensions(self):
        """测试错误维度输入。"""
        closes = np.array([[100.0, 101.0], [102.0, 103.0]])

        with self.assertRaises(ValueError) as context:
            EMACalculator.calculate(closes, period=2)

        self.assertIn("一维数组", str(context.exception))

    def test_get_last_valid_ema_with_valid_values(self):
        """测试获取最后一个有效EMA值。"""
        closes = np.array([100.0] * 25)

        ema = EMACalculator.calculate_ema20(closes)
        last_ema = EMACalculator.get_last_valid_ema(ema)

        self.assertIsNotNone(last_ema)
        self.assertIsInstance(last_ema, float)

    def test_get_last_valid_ema_all_nan(self):
        """测试全部NaN的情况。"""
        ema = np.array([np.nan] * 10)

        last_ema = EMACalculator.get_last_valid_ema(ema)

        self.assertIsNone(last_ema)

    def test_ema_rising_trend(self):
        """测试上涨趋势中的EMA计算。"""
        closes = np.array([100.0 + i * 2 for i in range(30)])

        ema = EMACalculator.calculate_ema20(closes)

        valid_ema = ema[~np.isnan(ema)]
        self.assertTrue(np.all(np.diff(valid_ema) > 0))

    def test_ema_falling_trend(self):
        """测试下跌趋势中的EMA计算。"""
        closes = np.array([150.0 - i * 2 for i in range(30)])

        ema = EMACalculator.calculate_ema20(closes)

        valid_ema = ema[~np.isnan(ema)]
        self.assertTrue(np.all(np.diff(valid_ema) < 0))


if __name__ == "__main__":
    unittest.main()
