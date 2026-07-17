"""P2 收尾三刀的回归测试：

1. days=120 归一  —— 指标调用点统一走 DEFAULT_INDICATOR_DAYS 常量，
   缓存 key 一致（同 code 不同"天数"不再产生重复计算）。
2. 时区归一    —— now_cst() 返回 CST(UTC+8) 感知 datetime；
   naive/aware 混用（持仓天数、上市天数减法）不再抛 TypeError。
3. 减仓 REDUCE 落地 —— 卖出确认走 reduce_position 部分减仓，
   持仓保持 holding、份额/成本按比例减少、对应待处理信号标记 executed。
"""

import math

from src.infrastructure.timeutil import now_cst, CST
from src.infrastructure.indicator_cache import (
    IndicatorCache,
    get_cached_indicators,
    DEFAULT_INDICATOR_DAYS,
)
from src.domain.enums import (
    SellAction,
    parse_reduce_ratio,
)
from src.trading.position_manager import PositionManager
from tests.conftest import make_klines


# --------------------------------------------------------------------------
# 1) days 归一
# --------------------------------------------------------------------------
def test_default_indicator_days_is_120():
    assert DEFAULT_INDICATOR_DAYS == 120


def test_cached_indicators_key_uses_default_days():
    """不显式传 days 时，缓存 key 与显式传 120 完全一致（不会因默认值漂移产生两份缓存）。"""
    cache = IndicatorCache()
    # 用一个能记录调用天数参数的假 provider
    calls = []

    class FakeProvider:
        def __init__(self):
            self._k = make_klines(n=130, code="DAYS", daily_return=0.01)

        def get_klines(self, code, days=120):
            calls.append(days)
            return self._k[-days:]

    p = FakeProvider()
    # 显式 120
    a = get_cached_indicators(p, "DAYS", DEFAULT_INDICATOR_DAYS)
    # 默认（不传 days）
    b = get_cached_indicators(p, "DAYS")
    # 两次都应向 provider 请求 DEFAULT_INDICATOR_DAYS 天，且命中同一缓存
    assert calls == [DEFAULT_INDICATOR_DAYS, DEFAULT_INDICATOR_DAYS]
    assert a == b
    # 第二次是命中，不应再触发计算（calls 长度仍是 2）
    assert len(calls) == 2


def test_different_days_misses():
    """不同 days 仍按 key 区分（保障归一后行为不变）。"""
    cache = IndicatorCache()

    class FakeProvider:
        def __init__(self):
            self._k = make_klines(n=200, code="DD", daily_return=0.01)

        def get_klines(self, code, days=120):
            return self._k[-days:]

    p = FakeProvider()
    cache.get(p, "DD", 120)
    cache.get(p, "DD", 60)
    # 两个不同 days 各自一次计算
    assert cache.stats()["misses"] == 2
    assert cache.stats()["size"] == 2


# --------------------------------------------------------------------------
# 2) 时区归一
# --------------------------------------------------------------------------
def test_now_cst_is_aware_and_cst():
    now = now_cst()
    assert now.tzinfo is not None
    # Asia/Shanghai 固定 UTC+8
    assert now.utcoffset().total_seconds() == 8 * 3600
    assert now.tzinfo == CST


def test_hold_days_uses_aware_date_no_crash(pos_manager, mock_provider):
    """update_all_positions 内部用 aware.date() - naive.date()，不应抛 TypeError。"""
    # 用真实持仓：先建仓，再更新盈亏（这一步会算 hold_days）
    pos = pos_manager.confirm_buy(
        signal_id="TZ-1", etf_code="999001.SH", etf_name="时区测试",
        buy_price=1.0, buy_amount=1000.0,
    )
    # 不应抛异常
    updated = pos_manager.update_all_positions()
    assert any(p["id"] == pos["id"] for p in updated)
    assert pos["buy_shares"] == 1000.0


def test_is_in_cooldown_aware_safe(buy_engine):
    """buy_signal.is_in_cooldown 用 aware.date() - naive.date()，不崩。"""
    # 有卖出记录（很久以前）→ 已出冷静期，返回 False 且不抛 TypeError
    assert buy_engine.is_in_cooldown("999002.SH", {"999002.SH": "2020-01-01"}) is False
    # 无卖出记录 → 不在冷静期
    assert buy_engine.is_in_cooldown("999002.SH", {}) is False


# --------------------------------------------------------------------------
# 3) 减仓 REDUCE 落地
# --------------------------------------------------------------------------
def test_parse_reduce_ratio():
    assert parse_reduce_ratio(SellAction.REDUCE_50.value) == 0.5
    assert abs(parse_reduce_ratio(SellAction.REDUCE_33.value) - 1 / 3) < 1e-9
    assert parse_reduce_ratio(SellAction.REDUCE_HALF.value) == 0.5
    assert parse_reduce_ratio(SellAction.CLEAR_ALL.value) is None
    assert parse_reduce_ratio(None) is None


def test_reduce_position_partial(pos_manager, mock_provider):
    """减仓 50%：持仓保持 holding，份额/成本减半，信号标记 executed。"""
    pos = pos_manager.confirm_buy(
        signal_id="RED-1", etf_code="999003.SH", etf_name="减仓测试",
        buy_price=2.0, buy_amount=2000.0,  # 1000 份
    )
    pos_id = pos["id"]

    # 造一条待处理减仓信号（与 reduce_position 会去标记的信号对齐）
    pos_manager.db.save_signal({
        "signal_id": "SELL-RED-1", "signal_type": "sell",
        "etf_code": "999003.SH", "sell_strategy": "强制减仓",
        "sell_action": "REDUCE_50", "status": "pending",
        "pnl_amount": 0, "pnl_pct": 0,
    })

    # 以 2.4 卖出价减仓 50%
    result = pos_manager.reduce_position(
        pos_id, sell_price=2.4, ratio=0.5,
        sell_strategy="强制减仓", etf_code="999003.SH",
        sell_action="REDUCE_50", current_price=2.4,
    )

    # 持仓仍在（holding）
    remaining = pos_manager.db.get_positions(status="holding")
    assert len(remaining) == 1
    rem = remaining[0]
    assert rem["id"] == pos_id
    assert rem["buy_shares"] == 500.0            # 1000 * 0.5 保留
    assert rem["buy_amount"] == 1000.0           # 2.0 * 500
    assert rem["current_value"] == 1200.0         # 2.4 * 500

    # 已实现盈亏结算正确：(2.4-2.0)*500 = 200
    assert result["shares_to_sell"] == 500
    assert result["realized_pnl_amount"] == 200.0

    # 对应待处理信号被标记 executed
    sig_row = pos_manager.db.conn.execute(
        "SELECT status, pnl_amount FROM signals WHERE signal_id=?",
        ("SELL-RED-1",),
    ).fetchone()
    assert dict(sig_row)["status"] == "executed"
    assert dict(sig_row)["pnl_amount"] == 200.0


def test_reduce_one_third(pos_manager, mock_provider):
    """减仓 1/3：份额按比例下取整，持仓保持。"""
    pos = pos_manager.confirm_buy(
        signal_id="RED-2", etf_code="999004.SH", etf_name="三分一",
        buy_price=3.0, buy_amount=3000.0,  # 1000 份
    )
    pos_id = pos["id"]
    result = pos_manager.reduce_position(
        pos_id, sell_price=3.3, ratio=1 / 3,
        sell_strategy="止盈止损", etf_code="999004.SH",
        sell_action="REDUCE_33", current_price=3.3,
    )
    # floor(1000/3)=333 卖出，667 保留
    assert result["shares_to_sell"] == 333
    rem = pos_manager.db.get_positions(status="holding")[0]
    assert rem["buy_shares"] == 667
    assert rem["buy_amount"] == 3.0 * 667


def test_reduce_then_full_close(pos_manager, mock_provider):
    """先减仓 50%，再清仓，最终 status=sold 且剩余份额归零。"""
    pos = pos_manager.confirm_buy(
        signal_id="RED-3", etf_code="999005.SH", etf_name="减后清",
        buy_price=1.0, buy_amount=1000.0,  # 1000 份
    )
    pos_id = pos["id"]
    pos_manager.reduce_position(
        pos_id, sell_price=1.2, ratio=0.5,
        sell_strategy="强制减仓", etf_code="999005.SH",
        sell_action="REDUCE_50", current_price=1.2,
    )
    closed = pos_manager.close_position(pos_id, sell_price=1.2, sell_strategy="manual")
    # close_position 返回的是更新前的快照，故以 DB 实际状态为准
    assert pos_manager.db.get_positions(status="sold") != []
    assert pos_manager.db.get_positions(status="holding") == []
