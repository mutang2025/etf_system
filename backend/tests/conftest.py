"""Pytest 固件与共享工具。

设计目标：
- 全程使用 mock 数据源（确定性，seed=42），不触碰真实网络。
- 每个测试使用独立的临时 SQLite 文件库（WAL 并发安全），不污染生产 etf.db。
- 提供 ScriptedProvider，可在单测中精确编排某只 ETF 的实时行情/K线，
  从而把"冲高回落累积""空头排列触发危险信号""量比确定性"等逻辑隔离验证。

注意：必须在任何 get_data_provider() 调用之前把 DATA_SOURCE 设为 mock，
否则单例会落到 akshare（真实网络）。这里在模块导入期就完成设置。
"""

import sys
import pathlib
import pytest

# 把 backend/ 加入 sys.path，使 `import config` 与 `from src...` 可用。
BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import datetime as _dt  # noqa: E402

# 必须在导入任何业务模块之前锁定数据源为 mock。
from config import settings  # noqa: E402

settings.DATA_SOURCE = "mock"

from src.infrastructure.mock_data_provider import (  # noqa: E402
    MockDataProvider,
    get_mock_provider,
)
from src.domain.entities import DailyKline  # noqa: E402
from src.infrastructure.database_repo import DatabaseRepository  # noqa: E402
from src.trading.sell_strategies import SellStrategyEngine  # noqa: E402
from src.trading.buy_signal import BuySignalEngine  # noqa: E402
from src.screening.screening_engine import ScreeningEngine  # noqa: E402
from src.trading.position_manager import PositionManager  # noqa: E402
from database import init_db  # noqa: E402


# --------------------------------------------------------------------------
# 测试辅助：可脚本化的数据源
# --------------------------------------------------------------------------
class ScriptedProvider:
    """包装真实 mock provider，允许按代码覆盖实时行情与 K 线。

    未在脚本中覆盖的代码，行为与原 mock provider 完全一致。
    """

    def __init__(self, base: MockDataProvider):
        self._base = base
        self._rt: dict = {}        # code -> 实时行情 dict
        self._klines: dict = {}    # code -> list[DailyKline]

    # --- 覆盖点 ---
    def set_realtime(self, code: str, **overrides) -> None:
        base_rt = dict(self._base.get_realtime_quote(code) or {})
        base_rt.setdefault("code", code)
        base_rt.update(overrides)
        self._rt[code] = base_rt

    def set_klines(self, code: str, klines: list) -> None:
        self._klines[code] = klines

    # --- 接口实现（优先返回脚本值）---
    def get_realtime_quote(self, code: str):
        if code in self._rt:
            return self._rt[code]
        return self._base.get_realtime_quote(code)

    def get_klines(self, code: str, days: int = 120):
        if code in self._klines:
            kl = self._klines[code]
            return kl[-days:] if days < len(kl) else kl
        return self._base.get_klines(code, days)

    def get_etf_pool(self):
        return self._base.get_etf_pool()

    def get_hs300_today_change(self):
        return self._base.get_hs300_today_change()

    def get_active_etfs(self):
        return self._base.get_active_etfs()

    # 其余方法全部透传
    def __getattr__(self, name):
        return getattr(self._base, name)


def make_klines(n: int = 70, code: str = "X", start: float = 2.0,
                daily_return: float = -0.01, base_vol: float = 1_000_000.0) -> list:
    """生成一段 K 线，用于构造特定技术形态。

    daily_return < 0  -> 严格下行 -> 空头排列（MA5<MA10<...<MA60 且收盘<MA5）
    daily_return > 0  -> 严格上行 -> 多头排列（空头排列为 False）
    """
    klines = []
    price = start
    d = _dt.date(2025, 1, 1)
    for i in range(n):
        close = price * (1 + daily_return)
        open_ = price
        high = max(open_, close) * 1.005
        low = min(open_, close) * 0.995
        klines.append(DailyKline(
            etf_code=code,
            trade_date=(d + _dt.timedelta(days=i)).strftime("%Y-%m-%d"),
            open=round(open_, 4),
            high=round(high, 4),
            low=round(low, 4),
            close=round(close, 4),
            volume=round(base_vol, 2),
            amount=round(base_vol * close / 10, 2),
        ))
        price = close
    return klines


class FakeDateTime:
    """可注入 `now()` 的 datetime 替身，用于测试交易时段与跨日缓存。"""

    _now = None

    @classmethod
    def now(cls, tz=None):
        return cls._now

    @classmethod
    def strptime(cls, *args, **kwargs):
        return _dt.datetime.strptime(*args, **kwargs)


# --------------------------------------------------------------------------
# Pytest 固件
# --------------------------------------------------------------------------
def _fresh_db(tmp_path) -> DatabaseRepository:
    """创建独立临时库并建表（不污染生产 etf.db）。"""
    db_path = tmp_path / "test.db"
    settings.DB_PATH = str(db_path)
    init_db(str(db_path))
    repo = DatabaseRepository()
    repo.sync_etf_pool()        # 镜像应用启动时的池同步
    repo.init_default_params()  # 写入 26 项默认策略参数
    return repo


@pytest.fixture
def mock_provider() -> MockDataProvider:
    """进程级 mock 单例（seed=42，数据确定）。"""
    return get_mock_provider()


@pytest.fixture
def db(tmp_path) -> DatabaseRepository:
    """每测试一个独立临时库。"""
    return _fresh_db(tmp_path)


@pytest.fixture
def sell_engine(mock_provider) -> SellStrategyEngine:
    return SellStrategyEngine(mock_provider)


@pytest.fixture
def buy_engine(mock_provider) -> BuySignalEngine:
    return BuySignalEngine(mock_provider)


@pytest.fixture
def screening(mock_provider) -> ScreeningEngine:
    return ScreeningEngine(mock_provider)


@pytest.fixture
def pos_manager(db, mock_provider) -> PositionManager:
    return PositionManager(db, mock_provider)


@pytest.fixture
def scripted(mock_provider) -> ScriptedProvider:
    """可脚本化数据源。"""
    return ScriptedProvider(mock_provider)
