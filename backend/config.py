"""Application configuration for ETF Quantitative Trading System."""

from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    """System configuration loaded from environment or defaults."""

    # Application
    APP_NAME: str = "ETF量化跟踪交易系统"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # Database
    DB_PATH: str = str(Path(__file__).parent / "data" / "etf.db")

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Trading parameters (defaults from PRD)
    TOTAL_CAPITAL: float = 100000.0          # 总资金（元）
    SINGLE_POSITION_LIMIT: float = 0.30      # 单只ETF仓位上限 30%
    TOTAL_POSITION_LIMIT: float = 0.80       # 总仓位上限 80%
    DAILY_SELECT_COUNT: int = 2              # 每日选股数量
    MOMENTUM_PERIOD: int = 20                 # 动量计算周期
    LIQUIDITY_THRESHOLD: float = 3000.0      # 日均成交额门槛（万元）
    MARKET_CAP_THRESHOLD: float = 80.0        # 总市值门槛（亿元）
    MARKET_DROP_THRESHOLD: float = -2.0      # 沪深300日跌幅空仓信号阈值
    SELL_COOLDOWN_DAYS: int = 5              # 卖出冷却期（交易日）

    # Buy signal parameters
    BUY_MA5_TOLERANCE: float = 0.015         # MA5回踩容忍度 1.5%
    BUY_VOLUME_SURGE_MULT: float = 2.0       # 主力资金异动倍数
    BUY_VOLUME_RATIO: float = 1.5            # 当日量/5日均量倍数
    BUY_SIGNAL_HOLD_SECONDS: int = 10        # 信号持续满足秒数（防假信号）

    # Sell strategy parameters
    EMERGENCY_LOSS_THRESHOLD: float = -5.0   # 紧急熔断浮亏阈值
    HIGH_OPEN_THRESHOLD: float = 2.0         # 高开幅度阈值
    HIGH_OPEN_DROP_THRESHOLD: float = -0.8   # 高开后回调阈值
    TREND_BREAK_MA_DAYS: int = 3             # 趋势破位未收回天数
    TAKE_PROFIT_THRESHOLD: float = 30.0     # 止盈阈值
    TAKE_PROFIT_STEP: float = 10.0           # 阶梯止盈步长
    STOP_LOSS_BASE: float = -6.0             # 基础止损
    STOP_LOSS_RELAXED: float = -7.2          # 持仓<5天放宽止损
    STOP_LOSS_TIGHTENED: float = -5.4        # 持仓>10天收紧止损
    PEAK_REVERSAL_RISE: float = 2.6          # 冲高回落日涨幅阈值
    PEAK_REVERSAL_DROP_1: float = 0.6        # 回落第一档
    PEAK_REVERSAL_DROP_2: float = 1.0        # 回落第二档
    PEAK_REVERSAL_DROP_3: float = 1.5        # 回落第三档
    MANDATORY_RISE: float = 3.5              # 强制减仓涨幅阈值
    MANDATORY_NO_NEW_HIGH_MIN: int = 5       # 未创新高分钟数
    ADX_THRESHOLD: float = 25.0              # ADX趋势动力阈值
    BB_STD_MULT: float = 2.0                # 布林带标准差倍数

    # Factor weights
    WEIGHT_TREND: float = 0.25
    WEIGHT_MOMENTUM: float = 0.20
    WEIGHT_VOLUME: float = 0.15
    WEIGHT_VOLATILITY: float = 0.10
    WEIGHT_TECHNICAL: float = 0.30

    # Real-time scan
    SCAN_INTERVAL_SECONDS: int = 10          # 盘中扫描间隔
    TRADING_START: str = "09:30"
    TRADING_END: str = "15:00"

    # Data source
    DATA_SOURCE: str = "akshare"             # "mock" or "akshare"

    class Config:
        env_file = ".env"


settings = Settings()
