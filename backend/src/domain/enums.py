"""Enums for the ETF trading system."""

from enum import Enum
from typing import Optional


class ETFType(str, Enum):
    A_STOCK = "A股"
    CROSS_BORDER = "跨境"


class ETFStatus(str, Enum):
    ACTIVE = "active"
    EXCLUDED = "excluded"
    BLACKLIST = "blacklist"
    WHITELIST = "whitelist"


class DataStatus(str, Enum):
    NORMAL = "normal"
    ABNORMAL = "abnormal"


class SignalType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    EMPTY = "empty"           # 空仓信号


class SignalStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SKIPPED = "skipped"
    EXECUTED = "executed"
    EXPIRED = "expired"


class PositionStatus(str, Enum):
    HOLDING = "holding"
    SOLD = "sold"


class SellStrategyType(str, Enum):
    EMERGENCY_CIRCUIT = "紧急熔断"
    HIGH_OPEN_DUMP = "高开砸盘"
    DANGER_SIGNAL = "危险信号"
    TREND_ANALYSIS = "趋势分析"
    TAKE_PROFIT_STOP_LOSS = "止盈止损"
    PEAK_REVERSAL = "冲高回落"
    MANDATORY_REDUCTION = "强制减仓"


class SellAction(str, Enum):
    CLEAR_ALL = "CLEAR_ALL"
    REDUCE_50 = "REDUCE_50"
    REDUCE_33 = "REDUCE_33"
    REDUCE_HALF = "REDUCE_HALF"
    STEP_PROFIT = "STEP_PROFIT"
    STOP_LOSS = "STOP_LOSS"


# 减仓动作 -> 卖出占当前持仓的比例。供卖出执行层（部分减仓）落地使用。
_SELL_REDUCE_RATIO = {
    SellAction.REDUCE_50.value: 0.5,
    SellAction.REDUCE_33.value: 1.0 / 3.0,
    SellAction.REDUCE_HALF.value: 0.5,
}


def parse_reduce_ratio(action: Optional[str]) -> Optional[float]:
    """返回减仓动作对应的卖出比例；非减仓动作（清仓/止损等）返回 ``None``。"""
    if action is None:
        return None
    return _SELL_REDUCE_RATIO.get(action)


class ParamGroup(str, Enum):
    SCREENING = "screening"
    FACTOR = "factor"
    BUY = "buy"
    SELL = "sell"
    PUSH = "push"


class PresetTemplate(str, Enum):
    CONSERVATIVE = "保守型"
    STANDARD = "标准型"
    AGGRESSIVE = "激进型"


class ScreeningLayer(str, Enum):
    """Four-layer funnel screening stages."""
    BASIC_FILTER = "基础筛选"
    MULTI_FACTOR = "多因子打分"
    THEME_CLUSTER = "题材聚类"
    RISK_FILTER = "深度风险过滤"
