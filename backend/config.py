"""Application configuration for ETF Quantitative Trading System."""

from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    """System configuration loaded from environment or defaults."""

    # Application
    APP_NAME: str = "ETF量化跟踪交易系统"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

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
    SCANNER_ENABLED: bool = True              # 启动时自动拉起盘中扫描守护进程

    # ETF pool auto-sync (交易日收盘后自动同步一次)
    POOL_SYNC_ENABLED: bool = True             # 启动时自动拉起池同步守护进程
    POOL_SYNC_AFTER: str = "15:30"           # 收盘后触发时刻（等数据落地，默认收盘15:00后半小时）

    # 四层选股自动运行（交易日收盘后自动跑一次四层选股，推荐结果入待买入池）
    SCREENING_ENABLED: bool = True            # 启动时自动拉起选股调度器
    SCREENING_AFTER: str = "15:30"          # 收盘后触发时刻（与池同步一致，等当日数据落地）

    # 自动交易（信号触发即自动成交，无需手动确认；默认关闭，安全优先）
    # 通过 strategy_params(auto_execute_buy / auto_execute_sell) 持久化，
    # 可在「信号中心」页面实时开关，set_param 会将值同步进本 settings 单例。
    AUTO_EXECUTE_BUY: bool = False            # 买入信号自动确认建仓
    AUTO_EXECUTE_SELL: bool = False           # 卖出信号自动执行（清仓/减仓）
    AUTO_SELL_COOLDOWN_SECONDS: int = 300     # 同一持仓同一策略的自动卖出最小间隔，防守护进程 10s 循环重复减仓

    # Data source
    DATA_SOURCE: str = "akshare"             # "mock" or "akshare"

    # Security (P1-3): 收紧 CORS + 可选 Bearer 鉴权
    # 受信前端源（逗号分隔）。为空时使用 "*"（仅本地开发，且关闭凭据）。
    # 一旦设置了 API_TOKEN，CORS 将强制收紧到本白名单，且所有写接口需 Bearer 鉴权。
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
    API_TOKEN: str = ""                        # 为空 = 开放模式（本地开发不鉴权）

    # Performance — ETF whitelist small pool + persistent K-line cache (real-data mode)
    # 真实数据（akshare）下，全市场 ~1500+ 只 ETF 逐只拉日 K 线会极慢；启用白名单小池后
    # 只扫描精选的高流动性 ETF，Layer2 取数从 O(全市场) 降到 O(白名单)。该开关仅在
    # DATA_SOURCE=="akshare" 时生效，mock 模式保持全池，不影响测试与演示。
    USE_WHITELIST_POOL: bool = True
    # 已去重：上证50(2) / A50系(3) / 红利(2) / 沪深300(纯指510300+159919、增强561990、质量563960、ESG159791)
    # 剔除跨市场沪港深300/500。每类仅留龙头与代表性策略，去重后共 100 只 A 股。
    ETF_WHITELIST: list = [
        "588000.SH",  # 科创50ETF华夏
        "510300.SH",  # 沪深300ETF华泰柏瑞（沪深300代表）
        "512880.SH",  # 证券ETF国泰
        "510050.SH",  # 上证50ETF华夏（上证50代表）
        "159919.SZ",  # 沪深300ETF嘉实（沪深300代表）
        "510100.SH",  # 上证50ETF易方达（上证50代表）
        "159611.SZ",  # 电力ETF广发
        "510760.SH",  # 上证指数ETF国泰
        "560280.SH",  # 工程机械ETF广发
        "512200.SH",  # 房地产ETF南方
        "515450.SH",  # 红利低波50ETF南方（红利代表）
        "510980.SH",  # 上证指数ETF汇添富
        "515230.SH",  # 软件ETF国泰
        "562550.SH",  # 绿电ETF华夏
        "530060.SH",  # 上证指数ETF易方达
        "561560.SH",  # 电力ETF华泰柏瑞
        "159256.SZ",  # 创业板软件ETF华夏
        "561580.SH",  # 央企红利ETF华泰柏瑞（央企红利代表）
        "159601.SZ",  # A50ETF华夏（MSCI中国A50代表）
        "159930.SZ",  # 能源ETF汇添富
        "159350.SZ",  # 深证50ETF富国
        "563860.SH",  # 中证A500ETF海富通
        "515970.SH",  # 工程机械ETF华夏
        "560710.SH",  # 船舶ETF富国
        "510180.SH",  # 上证180ETF华安
        "159625.SZ",  # 绿色电力ETF嘉实
        "513360.SH",  # 教育ETF博时
        "515060.SH",  # 房地产ETF华夏
        "562930.SH",  # 软件ETF易方达
        "562960.SH",  # 绿色电力ETF易方达
        "516970.SH",  # 基建ETF广发
        "510910.SH",  # 上证指数ETF南方
        "159107.SZ",  # 创业板软件ETF富国
        "560350.SH",  # 中证A50ETF摩根（中证A50代表）
        "159790.SZ",  # 碳中和ETF华夏
        "159590.SZ",  # 软件ETF汇添富
        "159565.SZ",  # 汽车零部件ETF易方达
        "561170.SH",  # 绿色电力ETF富国
        "159067.SZ",  # 绿色电力ETF鹏华
        "159226.SZ",  # 中证A500增强ETF国泰
        "159301.SZ",  # 公用事业ETF华夏
        "560450.SH",  # 电力ETF天弘
        "159380.SZ",  # A500ETF东财
        "562350.SH",  # 电力ETF银华
        "560830.SH",  # 电力ETF华夏
        "159623.SZ",  # 成渝经济圈ETF博时
        "159899.SZ",  # 软件ETF招商
        "515370.SH",  # 光伏ETF华夏
        "159046.SZ",  # 绿电ETF天弘
        "562700.SH",  # 汽车零部件ETF华夏
        "159686.SZ",  # A100ETF易方达（A100代表）
        "159177.SZ",  # 工程机械ETF鹏华
        "516370.SH",  # 电力ETF汇添富
        "159005.SZ",  # 快钱ETF汇添富
        "159609.SZ",  # 光伏ETF浦银
        "159639.SZ",  # 碳中和ETF南方
        "159586.SZ",  # 计算机ETF南方
        "561990.SH",  # 沪深300增强ETF招商（沪深300增强代表）
        "563650.SH",  # 中证A500ETF兴业
        "562810.SH",  # 上证指数增强ETF嘉实
        "560270.SH",  # 电力ETF工银
        "512140.SH",  # 电力ETF华安
        "560580.SH",  # 电力ETF南方
        "510810.SH",  # 上海国企ETF汇添富
        "159066.SZ",  # A股ETF建信
        "159641.SZ",  # 碳中和ETF招商
        "159061.SZ",  # 绿色电力ETF南方
        "159966.SZ",  # 创业板价值ETF华夏
        "560930.SH",  # 电力ETF易方达
        "562850.SH",  # 央企能源ETF嘉实
        "159253.SZ",  # 银行ETF博时
        "159298.SZ",  # 创业板50ETF大成
        "516250.SH",  # 工程机械ETF富国
        "530180.SH",  # 上证180ETF易方达
        "560480.SH",  # 电力ETF招商
        "159886.SZ",  # 机械ETF富国
        "560460.SH",  # 电力ETF平安
        "561700.SH",  # 电力ETF博时
        "159542.SZ",  # 工程机械ETF大成
        "512580.SH",  # 环保ETF广发
        "159861.SZ",  # 碳中和50ETF国泰
        "510570.SH",  # 中证500ETF兴业
        "530300.SH",  # 上证180ETF华泰柏瑞
        "510990.SH",  # 180ESGETF工银
        "159159.SZ",  # 公用事业ETF国投瑞银
        "560690.SH",  # 电信ETF鹏华
        "561130.SH",  # 国货ETF富国
        "159621.SZ",  # ESGETF国泰
        "159065.SZ",  # 工程机械ETF景顺
        "515990.SH",  # 一带一路ETF汇添富
        "510140.SH",  # 上证综指ETF华夏
        "530580.SH",  # 上证180ETF南方
        "517180.SH",  # 中国国企ETF南方
        "159872.SZ",  # 智能网联汽车ETF鹏华
        "561030.SH",  # 工程机械ETF华泰柏瑞
        "512650.SH",  # 长三角ETF汇添富
        "159009.SZ",  # 创业板新能源ETF易方达
        "563960.SH",  # 300质量ETF兴全（沪深300质量因子代表）
        "159161.SZ",  # 工程机械ETF东财
        "159791.SZ",  # 300ESGETF华夏（沪深300ESG因子代表）
    ]
    # 落盘 K 线缓存目录（跨重启持久，避免冷启动重新拉取全部 ETF 的日 K 线）
    KLINE_CACHE_DIR: str = str(Path(__file__).parent / "data" / "kline_cache")

    class Config:
        env_file = ".env"


settings = Settings()
