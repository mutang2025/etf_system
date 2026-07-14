"""Enums for the ETF trading system."""

from enum import Enum


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
    CLEAR_ALL = "清仓"
    REDUCE_50 = "减仓50%"
    REDUCE_33 = "卖出1/3"
    REDUCE_HALF = "卖出一半"
    STEP_PROFIT = "分步止盈"
    STOP_LOSS = "止损"


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
