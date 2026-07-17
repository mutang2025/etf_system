"""P2 — 指标/行情缓存：消除每轮扫描的 N+1 重算。

正交且与"买入扫描宇宙扩宽（P2 第一刀）"互补：扩宽把每轮扫描的 ETF
数量从 2 只放大到 ~11 只，若指标仍每轮重算，N+1 会被同步放大。
本刀用「进程级指标缓存」（按 (code, days, 最后K线日期) 作键）把每只 ETF
每天的指标计算压成一次，扫描/持仓/买入/选股四条路径共享同一份结果，
且当新日 K 线落地时键自然变化、自动失效。

全部用例基于 mock 数据源（seed=42，确定性），不触碰真实网络。
"""

from datetime import date, timedelta

from unittest import mock
from tests.conftest import make_klines

from src.indicators.technical import IndicatorCalculator as RealCalc
from src.infrastructure import indicator_cache as ic


class _SpyCalc(RealCalc):
    """继承真实计算器，仅记录实例化次数（即"重算"次数）。"""

    _calls = []

    def __init__(self, klines):
        _SpyCalc._calls.append(klines)
        super().__init__(klines)


def _reset_spy():
    _SpyCalc._calls = []


# --------------------------------------------------------------------------
# 1) 同一 ETF 多次取指标：只重算一次（cache hit）
# --------------------------------------------------------------------------
def test_indicator_calculator_called_once_per_code(mock_provider):
    cache = ic.get_indicator_cache()
    cache.invalidate()
    code = "512480.SH"  # mock 含 120 日 K 线

    _reset_spy()
    with mock.patch("src.infrastructure.indicator_cache.IndicatorCalculator", _SpyCalc):
        r1 = ic.get_cached_indicators(mock_provider, code)
        r2 = ic.get_cached_indicators(mock_provider, code)

    assert r1 and r2, "两次都应返回非空指标"
    assert r1["RSI"] == r2["RSI"], "命中缓存应返回确定性一致的结果"
    assert len(_SpyCalc._calls) == 1, "同一 ETF 同日应只重算一次指标"


# --------------------------------------------------------------------------
# 2) 最后一根 K 线日期变化 → 自动失效并重算
# --------------------------------------------------------------------------
def test_invalidation_on_new_daily_bar(scripted):
    cache = ic.get_indicator_cache()
    cache.invalidate()
    code = "TEST.CACHE"  # 不在 mock 池内，避免干扰

    k1 = make_klines(n=70, code=code, daily_return=0.01)
    # 把所有 trade_date 往后挪 1 天 → 最后一根 K 线日期变化
    k2 = [
        k.__class__(
            etf_code=k.etf_code,
            trade_date=(date(*map(int, k.trade_date.split("-"))) + timedelta(days=1)).strftime("%Y-%m-%d"),
            open=k.open, high=k.high, low=k.low, close=k.close,
            volume=k.volume, amount=k.amount,
        )
        for k in k1
    ]

    _reset_spy()
    with mock.patch("src.infrastructure.indicator_cache.IndicatorCalculator", _SpyCalc):
        scripted.set_klines(code, k1)
        ic.get_cached_indicators(scripted, code)   # 首次：重算
        scripted.set_klines(code, k2)                 # 新日 K 线落地
        ic.get_cached_indicators(scripted, code)   # 键变化：应重新重算

    assert len(_SpyCalc._calls) == 2, "新日 K 线应触发一次失效后重算"


# --------------------------------------------------------------------------
# 3) is_trend_stock 由缓存指标派生，不再单独算
# --------------------------------------------------------------------------
def test_is_trend_stock_derived_from_cache(scripted):
    cache = ic.get_indicator_cache()
    cache.invalidate()
    code = "TEST.TREND"

    # 严格上行 → 多头排列 → is_trend_stock 应为 True
    klines = make_klines(n=70, code=code, daily_return=0.01)
    scripted.set_klines(code, klines)

    _reset_spy()
    with mock.patch("src.infrastructure.indicator_cache.IndicatorCalculator", _SpyCalc):
        direct = ic.get_cached_indicators(scripted, code)
        derived = ic.is_trend_stock_cached(scripted, code)
        again = ic.is_trend_stock_cached(scripted, code)  # 应命中

    assert direct.get("is_trend_stock") is True, "上行序列应判为趋势股"
    assert derived is True
    # 三次取用（一次全量 + 两次 is_trend）只重算一次
    assert len(_SpyCalc._calls) == 1, "is_trend_stock 不应触发额外重算"


# --------------------------------------------------------------------------
# 4) 跨模块共享：买入/卖出/持仓三条路径只重算一次
# --------------------------------------------------------------------------
def test_cross_module_sharing(pos_manager, buy_engine, sell_engine, mock_provider):
    cache = ic.get_indicator_cache()
    cache.invalidate()
    code = "512480.SH"
    rt = mock_provider.get_realtime_quote(code)
    buy_price = rt["price"]

    _reset_spy()
    with mock.patch("src.infrastructure.indicator_cache.IndicatorCalculator", _SpyCalc):
        # 持仓经理 confirm_buy：经缓存派生 is_trend_stock（重算 #1）
        pos = pos_manager.confirm_buy(
            "BUY-CACHE-T01", code, "半导体ETF", buy_price, 100.0
        )
        # 买入引擎 check_buy_conditions：取全量指标（命中）
        buy_engine.check_buy_conditions(code)
        # 卖出引擎 check_all_strategies：取全量指标（命中）
        sell_engine.check_all_strategies({
            "etf_code": code, "etf_name": "半导体ETF",
            "buy_price": buy_price, "buy_shares": 10,
            "buy_date": "2026-01-01", "hold_days": 5,
            "is_trend_stock": False, "current_price": buy_price,
        })

    assert len(_SpyCalc._calls) == 1, (
        "买入/卖出/持仓三条路径应共享同一份指标，只重算一次"
    )
    # 清理：撤销刚建的持仓，避免影响其他用例
    pos_manager.close_position(pos["id"], buy_price, "test_cleanup")


# --------------------------------------------------------------------------
# 5) 两次完整选股：第二次指标全部命中缓存（0 次重算）
#    同时证明同一次 run_full_screening 内 layer4 复用了 layer2 已算的指标
# --------------------------------------------------------------------------
def test_screening_indicators_cached_across_runs(screening, mock_provider):
    cache = ic.get_indicator_cache()
    cache.invalidate()

    _reset_spy()
    with mock.patch("src.infrastructure.indicator_cache.IndicatorCalculator", _SpyCalc):
        screening.run_full_screening()            # 首次：全量重算
        first_calls = len(_SpyCalc._calls)
        screening.run_full_screening()            # 第二次：键未变 → 全命中
        second_calls = len(_SpyCalc._calls) - first_calls

    assert first_calls > 0, "首次选股应产生指标计算"
    assert second_calls == 0, (
        "第二次完整选股指标应 100% 命中缓存，重算次数为 0"
        "（也即扩宽后每轮守护进程扫描不再重复重算）"
    )


# --------------------------------------------------------------------------
# 6) 健康检查可见缓存命中率（observability）
# --------------------------------------------------------------------------
def test_cache_stats_reported(mock_provider):
    cache = ic.get_indicator_cache()
    cache.invalidate()
    code = "512480.SH"
    ic.get_cached_indicators(mock_provider, code)
    ic.get_cached_indicators(mock_provider, code)  # 命中一次
    stats = cache.stats()
    assert stats["size"] >= 1
    assert stats["misses"] >= 1
    assert stats["hits"] >= 1
    assert stats["hit_rate"] > 0
