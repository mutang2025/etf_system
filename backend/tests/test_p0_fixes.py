"""P0 回归测试：策略参数真正作用于引擎 + 扫描守护进程与路由共享选股单例。

P0-1：此前前端「策略参数」写入 strategy_params 表，但 set_param 从不回写
      config.settings，而 buy/sell/screening 引擎读取的是 config.settings，
      导致调参对选股/信号零影响（装饰性功能）。
P0-2：realtime_scanner 自建 ScreeningEngine 实例，与路由的 get_screening()
      单例不是同一个对象；手动「运行选股」只清了路由侧缓存，守护进程当天
      仍抱旧推荐。修复后两者共享同一单例（含同一份当日推荐缓存）。
"""

import asyncio

import pytest

from config import settings
from src.screening.screening_engine import get_screening
from src.realtime_scanner import get_scanner
from src.presentation import routes


# 26 个可调参数对应的 settings 字段（用于在测试间隔离，避免污染全局单例）
_PARAM_KEYS = [
    "TOTAL_CAPITAL", "SINGLE_POSITION_LIMIT", "TOTAL_POSITION_LIMIT",
    "DAILY_SELECT_COUNT", "MOMENTUM_PERIOD", "LIQUIDITY_THRESHOLD",
    "MARKET_CAP_THRESHOLD", "MARKET_DROP_THRESHOLD", "BUY_MA5_TOLERANCE",
    "BUY_VOLUME_SURGE_MULT", "BUY_VOLUME_RATIO", "WEIGHT_TREND",
    "WEIGHT_MOMENTUM", "WEIGHT_VOLUME", "WEIGHT_VOLATILITY", "WEIGHT_TECHNICAL",
    "HIGH_OPEN_THRESHOLD", "HIGH_OPEN_DROP_THRESHOLD", "TAKE_PROFIT_THRESHOLD",
    "TAKE_PROFIT_STEP", "STOP_LOSS_BASE", "STOP_LOSS_RELAXED",
    "STOP_LOSS_TIGHTENED", "PEAK_REVERSAL_RISE", "MANDATORY_RISE", "ADX_THRESHOLD",
]


@pytest.fixture(autouse=True)
def _snapshot_settings():
    """每个测试前后还原 settings 单例，避免跨测试污染（settings 是进程级单例）。"""
    saved = {k: getattr(settings, k) for k in _PARAM_KEYS}
    yield
    for k, v in saved.items():
        setattr(settings, k, v)
    get_screening().invalidate_cache()


# ============================ P0-1 ============================

def test_set_param_updates_settings_float(db):
    """因子权重（float）写入后，config.settings 立即同步。"""
    db.set_param("weight_trend", "0.50", "factor")
    assert settings.WEIGHT_TREND == 0.50
    assert isinstance(settings.WEIGHT_TREND, float)


def test_set_param_updates_settings_int(db):
    """选股数量/周期（int）写入后，config.settings 同步且类型保持 int。"""
    db.set_param("daily_select_count", "5", "screening")
    db.set_param("momentum_period", "30", "screening")
    assert settings.DAILY_SELECT_COUNT == 5
    assert isinstance(settings.DAILY_SELECT_COUNT, int)
    assert settings.MOMENTUM_PERIOD == 30
    assert isinstance(settings.MOMENTUM_PERIOD, int)


def test_set_param_updates_settings_total_capital(db):
    """总资金（float）写入后同步，并保留浮点类型。"""
    db.set_param("total_capital", "200000", "screening")
    assert settings.TOTAL_CAPITAL == 200000.0
    assert isinstance(settings.TOTAL_CAPITAL, float)


def test_set_param_unknown_key_is_ignored(db):
    """库中不存在对应 settings 字段的 key 不应报错，也不应产生副作用。"""
    before = settings.APP_NAME
    db.set_param("not_a_real_key", "123", "screening")  # 不应抛异常
    assert settings.APP_NAME == before


def test_load_params_into_settings_from_db(db):
    """load_params_into_settings 读库并批量回写 settings（覆盖重启后从库恢复）。"""
    # 直接改一行已有参数（adx_threshold 已由 init_default_params 写入），
    # 不走 set_param，专门验证「批量从库加载」这条路径
    db.conn.execute(
        "UPDATE strategy_params SET param_value='40' WHERE param_key='adx_threshold'"
    )
    db.conn.commit()
    db.load_params_into_settings()
    assert settings.ADX_THRESHOLD == 40.0


def test_engine_actually_uses_updated_weight(db):
    """最强证明：调权后引擎实际输出的因子权重跟着变（引擎读取的是 live settings）。"""
    db.set_param("weight_trend", "0.99", "factor")
    screening = get_screening()
    results = screening.run_full_screening()
    trend_weight = None
    for r in results:
        if r.factor_scores:
            for f in r.factor_scores:
                if f.factor_name == "趋势强度":
                    trend_weight = f.weight
                    break
        if trend_weight is not None:
            break
    assert trend_weight == 0.99, f"引擎未采用更新后的权重，实际={trend_weight}"


def test_set_param_factor_invalidates_cache(db):
    """因子类参数变更应使当日推荐缓存失效，下一轮扫描自动重算（修 P0-1 副作用）。"""
    screening = get_screening()
    # 先填充缓存
    screening.get_today_recommendations()
    assert screening._rec_cache, "前置条件：缓存应已填充"
    # 改因子权重 -> 触发缓存失效
    db.set_param("weight_momentum", "0.05", "factor")
    assert screening._rec_cache == {}, "因子参数变更后当日推荐缓存应被清空"


# ============================ P0-2 ============================

def test_scanner_shares_screening_singleton(db):
    """守护进程与路由使用同一个 ScreeningEngine 单例（含同一份推荐缓存）。"""
    scanner = get_scanner()
    assert scanner.screening is get_screening()


def test_manual_run_screening_invalidates_shared_cache(db):
    """手动「运行选股」使路由侧缓存失效，守护进程（同单例）下一轮即取到新推荐。

    直接调用路由函数 run_screening() 验证端到端：它内部会调用
    get_screening().invalidate_cache()，而该单例正是守护进程持有的同一个。
    """
    screening = get_screening()
    # 先填充缓存，模拟守护进程已跑过一轮
    screening.get_today_recommendations()
    assert screening._rec_cache, "前置条件：缓存应已填充"

    # 手动运行选股（与前端「运行选股」按钮走同一路径）
    asyncio.run(routes.run_screening())

    # 共享单例的缓存应被清空 -> 守护进程下一轮买入扫描会重算最新推荐
    assert screening._rec_cache == {}, "运行选股后共享单例缓存应被清空"
    # 守护进程持有的正是这个被清空的单例
    assert get_scanner().screening is screening
