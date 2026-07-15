"""技术指标测试：空头排列(P3) + 基础指标正确性。"""

import numpy as np
import pandas as pd

from src.indicators.technical import (
    check_bearish_arrangement,
    calc_rsi,
    calc_bollinger,
    calc_volume_ratio,
)
from conftest import make_klines


def _close_series(n=70, daily_return=-0.01, start=2.0) -> pd.Series:
    kl = make_klines(n=n, daily_return=daily_return, start=start)
    return pd.Series([k.close for k in kl])


def test_bearish_arrangement_true_on_declining():
    """P3: 严格下行的序列应判为空头排列（修复后稳定触发）。"""
    close = _close_series(daily_return=-0.012)
    assert check_bearish_arrangement(close) is True


def test_bearish_arrangement_false_on_rising():
    """上行序列不应判为空头排列。"""
    close = _close_series(daily_return=+0.012)
    assert check_bearish_arrangement(close) is False


def test_bearish_arrangement_false_when_too_short():
    """数据不足 61 个交易日时保守返回 False。"""
    close = _close_series(n=40, daily_return=-0.02)
    assert check_bearish_arrangement(close) is False


def test_rsi_monotonic_up_is_high():
    """纯上行收盘价 -> RSI 接近 100。"""
    close = pd.Series(np.linspace(1, 2, 30))
    rsi = calc_rsi(close, 14).iloc[-1]
    assert rsi > 95


def test_bollinger_returns_three_bands():
    close = pd.Series(np.linspace(1, 2, 30))
    upper, middle, lower = calc_bollinger(close, 20, 2.0)
    assert upper.iloc[-1] > middle.iloc[-1] > lower.iloc[-1]


def test_volume_ratio_above_one_when_recent_heavier():
    vol = pd.Series([100] * 15 + [300] * 5)
    assert calc_volume_ratio(vol) > 1.0
