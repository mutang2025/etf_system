"""Technical indicator calculations using numpy/pandas.

Implements all indicators referenced in the PRD:
- MA (5/10/20/30/60)
- RSI (14-day)
- MACD (12/26/9)
- Bollinger Bands (20-day, 2 std)
- ADX (14-day)
- Volume-Price Divergence
- Five-fold Death Cross
- Linear Regression Slope (trend strength)
- Momentum (5d/10d returns)
- Volume Ratio
- Annualized Volatility
- KDJ-J, OBV, BIAS, VR
"""

import numpy as np
import pandas as pd
from typing import Optional
import sys
sys.path.insert(0, '.')

from config import settings


def sma(series: pd.Series, length: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=length, min_periods=length).mean()


def ema(series: pd.Series, length: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=length, adjust=False).mean()


def calc_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Relative Strength Index."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=length, min_periods=length).mean()
    avg_loss = loss.rolling(window=length, min_periods=length).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    # 零下跌（有上涨）-> RSI=100；零下跌且零上涨 -> 保持中性 50
    rsi = rsi.where(avg_loss != 0, np.where(avg_gain > 0, 100.0, 50.0))
    return rsi.fillna(50)


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD line, signal line, and histogram."""
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    macd_hist = macd_line - signal_line
    return macd_line, signal_line, macd_hist


def calc_bollinger(close: pd.Series, length: int = 20, std_mult: float = 2.0):
    """Bollinger Bands: upper, middle, lower."""
    middle = sma(close, length)
    std = close.rolling(window=length, min_periods=length).std()
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    return upper, middle, lower


def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Average Directional Index."""
    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0)

    # Smoothed
    atr = tr.rolling(window=length, min_periods=length).mean()
    plus_di = 100 * (plus_dm.rolling(window=length, min_periods=length).mean() / atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm.rolling(window=length, min_periods=length).mean() / atr.replace(0, np.nan))

    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx = dx.rolling(window=length, min_periods=length).mean()
    return adx.fillna(25)


def calc_linear_regression_slope(close: pd.Series, length: int = 20) -> float:
    """Linear regression slope for trend strength.

    Returns the slope of the linear regression line over the last `length` days.
    Positive slope = uptrend, negative = downtrend.
    """
    recent = close.tail(length).dropna()
    if len(recent) < length:
        return 0.0
    x = np.arange(len(recent), dtype=float)
    y = recent.values
    # OLS slope: cov(x,y) / var(x)
    x_mean = x.mean()
    y_mean = y.mean()
    cov_xy = ((x - x_mean) * (y - y_mean)).sum()
    var_x = ((x - x_mean) ** 2).sum()
    if var_x == 0:
        return 0.0
    slope = cov_xy / var_x
    return float(slope)


def calc_momentum(close: pd.Series) -> float:
    """Momentum score: 5-day return * 0.6 + 10-day return * 0.4."""
    if len(close) < 11:
        return 0.0
    ret_5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100
    ret_10d = (close.iloc[-1] / close.iloc[-11] - 1) * 100
    return float(ret_5d * 0.6 + ret_10d * 0.4)


def calc_volume_ratio(volume: pd.Series, short: int = 5, long: int = 20) -> float:
    """Average volume ratio: 5-day avg volume / 20-day avg volume."""
    if len(volume) < long:
        return 1.0
    avg_5 = volume.tail(short).mean()
    avg_20 = volume.tail(long).mean()
    if avg_20 == 0:
        return 1.0
    return float(avg_5 / avg_20)


def calc_annualized_volatility(close: pd.Series, length: int = 20) -> float:
    """Annualized standard deviation of daily returns."""
    if len(close) < length + 1:
        return 0.0
    returns = close.tail(length + 1).pct_change().dropna()
    if len(returns) < 2:
        return 0.0
    std = returns.std()
    # Annualize: std * sqrt(252 trading days)
    annual_std = std * np.sqrt(252)
    return float(annual_std * 100)  # as percentage


def calc_kdj_j(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 9) -> float:
    """KDJ-J value (the most sensitive line)."""
    if len(close) < length:
        return 50.0
    recent_high = high.tail(length).max()
    recent_low = low.tail(length).min()
    if recent_high == recent_low:
        return 50.0
    rsv = (close.iloc[-1] - recent_low) / (recent_high - recent_low) * 100
    # Simplified J = 3*RSV - 100 (assuming K=D=RSV for simplification)
    j = 3 * rsv - 100
    return float(j)


def calc_obv(close: pd.Series, volume: pd.Series) -> float:
    """On Balance Volume trend direction (1=up, -1=down)."""
    if len(close) < 2:
        return 0.0
    obv = 0
    for i in range(1, len(close)):
        if close.iloc[i] > close.iloc[i - 1]:
            obv += volume.iloc[i]
        elif close.iloc[i] < close.iloc[i - 1]:
            obv -= volume.iloc[i]
    # Normalize: return direction
    return 1.0 if obv > 0 else -1.0


def calc_bias(close: pd.Series, length: int = 20) -> float:
    """BIAS: deviation from MA as percentage."""
    if len(close) < length:
        return 0.0
    ma = close.tail(length).mean()
    if ma == 0:
        return 0.0
    return float((close.iloc[-1] / ma - 1) * 100)


def calc_vr(close: pd.Series, volume: pd.Series, length: int = 20) -> float:
    """Volume Ratio: up-day volume / down-day volume."""
    if len(close) < length + 1:
        return 1.0
    recent_close = close.tail(length + 1)
    recent_vol = volume.tail(length)
    up_vol = 0.0
    down_vol = 0.0
    for i in range(1, len(recent_close)):
        if recent_close.iloc[i] > recent_close.iloc[i - 1]:
            up_vol += recent_vol.iloc[i - 1]
        elif recent_close.iloc[i] < recent_close.iloc[i - 1]:
            down_vol += recent_vol.iloc[i - 1]
    if down_vol == 0:
        return 2.0
    return float(up_vol / down_vol)


def check_bearish_arrangement(close: pd.Series) -> bool:
    """五重死叉 / 空头排列判定。

    PRD 与 README 实际语义为「空头排列」：短期均线完全位于长期均线下方且
    向下发散（MA5 < MA10 < MA20 < MA30 < MA60），且收盘价低于 MA5。
    原实现要求四对均线「同一天」同时下穿，真实市场几乎不可能发生，导致
    该风控首关长期失效。改为空头排列后，空头趋势中可稳定触发。
    """
    if len(close) < 61:
        return False

    ma5 = sma(close, 5).iloc[-1]
    ma10 = sma(close, 10).iloc[-1]
    ma20 = sma(close, 20).iloc[-1]
    ma30 = sma(close, 30).iloc[-1]
    ma60 = sma(close, 60).iloc[-1]

    if any(np.isnan(v) for v in [ma5, ma10, ma20, ma30, ma60]):
        return False

    bearish = ma5 < ma10 < ma20 < ma30 < ma60
    price_below = close.iloc[-1] < ma5
    return bool(bearish and price_below)


def check_volume_price_divergence(close: pd.Series, volume: pd.Series, lookback: int = 10) -> bool:
    """Check if price makes new high but volume doesn't (divergence).

    Condition: current price >= 99% of recent high, but current volume < 80% of high-day volume.
    """
    if len(close) < lookback or len(volume) < lookback:
        return False

    recent_close = close.tail(lookback)
    recent_vol = volume.tail(lookback)
    price_high = recent_close.max()
    # Use iloc + values.argmax() for position-based indexing
    high_idx = recent_close.values.argmax()
    vol_at_price_high = recent_vol.iloc[high_idx]

    current_price = close.iloc[-1]
    current_vol = volume.iloc[-1]

    # Price near high but volume doesn't confirm
    return current_price >= price_high * 0.99 and current_vol < vol_at_price_high * 0.8


def check_bollinger_breakout(close: pd.Series, std_mult: float = 2.0) -> bool:
    """Check if price breaks above the Bollinger upper band."""
    if len(close) < 20:
        return False
    upper, middle, lower = calc_bollinger(close, 20, std_mult)
    if upper.isna().iloc[-1]:
        return False
    return close.iloc[-1] > upper.iloc[-1]


def check_adx_danger(high: pd.Series, low: pd.Series, close: pd.Series, threshold: float = 25.0) -> bool:
    """Check if ADX indicates weakening trend (below threshold)."""
    if len(close) < 28:  # ADX needs sufficient data
        return False
    adx = calc_adx(high, low, close, 14)
    if adx.isna().iloc[-1]:
        return False
    return adx.iloc[-1] < threshold


def is_uptrend_arrangement(close: pd.Series) -> bool:
    """Check if MAs are in bullish arrangement: MA5 > MA10 > MA20 and price above MA20."""
    if len(close) < 21:
        return False
    ma5 = sma(close, 5).iloc[-1]
    ma10 = sma(close, 10).iloc[-1]
    ma20 = sma(close, 20).iloc[-1]
    if any(np.isnan(v) for v in [ma5, ma10, ma20]):
        return False
    return ma5 > ma10 > ma20 and close.iloc[-1] > ma20


def is_trend_stock(close: pd.Series, open_: pd.Series) -> bool:
    """Check if ETF qualifies as a trend stock.

    Criteria:
    - MA5 > MA10 > MA20 (bullish arrangement)
    - Price above MA20
    - At least 7 of last 10 days: close > open
    """
    if len(close) < 21 or len(open_) < 21:
        return False
    if not is_uptrend_arrangement(close):
        return False
    recent_close = close.tail(10)
    recent_open = open_.tail(10)
    up_days = (recent_close > recent_open).sum()
    return bool(up_days >= 7)  # Python bool (numpy bool_ is not JSON-serializable)


def check_trend_break(close: pd.Series, ma_days: int = 20, break_days: int = 3) -> bool:
    """Check if trend is truly broken: price below MA20 for `break_days` consecutive days."""
    if len(close) < ma_days + break_days:
        return False
    ma = sma(close, ma_days)
    recent_close = close.tail(break_days)
    recent_ma = ma.tail(break_days)
    # All days below MA and not recovered
    return all(recent_close.iloc[i] < recent_ma.iloc[i] for i in range(break_days) if not np.isnan(recent_ma.iloc[i]))


class IndicatorCalculator:
    """Calculate all indicators for an ETF from K-line data."""

    def __init__(self, klines: list):
        """Initialize with list of DailyKline objects."""
        if not klines:
            self.df = pd.DataFrame()
            return
        self.df = pd.DataFrame([
            {
                "date": k.trade_date,
                "open": k.open,
                "high": k.high,
                "low": k.low,
                "close": k.close,
                "volume": k.volume,
                "amount": k.amount,
            }
            for k in klines
        ])

    def get_all_indicators(self) -> dict:
        """Return all calculated indicators as a dict."""
        if self.df.empty:
            return {}

        close = self.df["close"]
        high = self.df["high"]
        low = self.df["low"]
        volume = self.df["volume"]
        open_ = self.df["open"]

        # Moving averages
        ma_dict = {}
        for period in [5, 10, 20, 30, 60]:
            ma_dict[f"MA{period}"] = sma(close, period).iloc[-1] if len(close) >= period else None

        return {
            "MA": ma_dict,
            "RSI": calc_rsi(close, 14).iloc[-1] if len(close) >= 14 else None,
            "MACD": self._get_macd_info(close),
            "BB": self._get_bollinger_info(close),
            "ADX": calc_adx(high, low, close, 14).iloc[-1] if len(close) >= 28 else None,
            "trend_slope": calc_linear_regression_slope(close, 20),
            "momentum": calc_momentum(close),
            "volume_ratio": calc_volume_ratio(volume),
            "annualized_volatility": calc_annualized_volatility(close, 20),
            "KDJ_J": calc_kdj_j(high, low, close, 9),
            "OBV_direction": calc_obv(close, volume),
            "BIAS": calc_bias(close, 20),
            "VR": calc_vr(close, volume, 20),
            "is_uptrend_arrangement": is_uptrend_arrangement(close),
            "is_trend_stock": is_trend_stock(close, open_),
            "trend_break": check_trend_break(close, 20, 3),
            "bearish_arrangement": check_bearish_arrangement(close),
            "death_cross": check_bearish_arrangement(close),  # 兼容键：实际语义为空头排列
            "volume_price_divergence": check_volume_price_divergence(close, volume, 10),
            "bollinger_breakout": check_bollinger_breakout(close, settings.BB_STD_MULT),
            "adx_danger": check_adx_danger(high, low, close, settings.ADX_THRESHOLD),
        }

    def _get_macd_info(self, close: pd.Series) -> dict:
        """Return MACD line, signal, and histogram values."""
        if len(close) < 26:
            return {"line": None, "signal": None, "hist": None, "is_golden_cross": False}
        macd_line, signal_line, macd_hist = calc_macd(close)
        # Golden cross: MACD line crosses above signal line
        is_golden = (macd_line.iloc[-1] > signal_line.iloc[-1] and
                     macd_line.iloc[-2] <= signal_line.iloc[-2])
        return {
            "line": round(float(macd_line.iloc[-1]), 6) if not np.isnan(macd_line.iloc[-1]) else None,
            "signal": round(float(signal_line.iloc[-1]), 6) if not np.isnan(signal_line.iloc[-1]) else None,
            "hist": round(float(macd_hist.iloc[-1]), 6) if not np.isnan(macd_hist.iloc[-1]) else None,
            "is_golden_cross": is_golden,
        }

    def _get_bollinger_info(self, close: pd.Series) -> dict:
        """Return Bollinger band values and position."""
        if len(close) < 20:
            return {"upper": None, "middle": None, "lower": None, "position": None}
        upper, middle, lower = calc_bollinger(close, 20, settings.BB_STD_MULT)
        u = upper.iloc[-1]
        m = middle.iloc[-1]
        l = lower.iloc[-1]
        c = close.iloc[-1]
        # Position: 0 = at lower band, 1 = at upper band
        if u == l:
            pos = 0.5
        else:
            pos = (c - l) / (u - l)
        return {
            "upper": round(float(u), 4) if not np.isnan(u) else None,
            "middle": round(float(m), 4) if not np.isnan(m) else None,
            "lower": round(float(l), 4) if not np.isnan(l) else None,
            "position": round(float(pos), 4),
        }
