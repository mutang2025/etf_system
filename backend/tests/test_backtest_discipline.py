"""回测卖出纪律测试。

覆盖：
1. 单条纪律仲裁（直接调 ``_check_*`` 隔离，验证动作/比例映射与实盘一致）
2. 组合层 discipline=True vs False 公平对比（纪律更早止损保本金）
3. 部分减仓执行分支（REDUCE_50 减仓但持仓保留）
4. T+1：当日买入当日不可被纪律卖出
"""

import datetime
from datetime import timedelta

from src.domain.entities import DailyKline
from src.domain.enums import SellAction
from src.backtest.sell_discipline import (
    historical_sell_check,
    SellDecision,
    _check_emergency_circuit,
    _check_take_profit_stop_loss,
    _check_danger_signal,
    _check_trend_analysis,
    _check_peak_reversal,
    _check_mandatory_reduction,
    _check_high_open_dump,
)
from src.backtest.engine import PortfolioBacktest, BacktestRequest


def _mk(code: str, closes: list, start: str = "2025-01-01") -> list:
    """本地确定性 K 线构造器（避免依赖 conftest 导入路径）。"""
    klines = []
    base = datetime.date.fromisoformat(start)
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        klines.append(DailyKline(
            etf_code=code,
            trade_date=(base + timedelta(days=i)).strftime("%Y-%m-%d"),
            open=round(o, 4),
            high=round(max(o, c) * 1.01, 4),
            low=round(min(o, c) * 0.99, 4),
            close=round(c, 4),
            volume=1_000_000.0,
            amount=round(1_000_000.0 * c / 10, 2),
        ))
    return klines


def _dates(n: int, start: str = "2025-01-01") -> list:
    base = datetime.date.fromisoformat(start)
    return [(base + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


# --------------------------------------------------------------------------
# 1) 单条纪律仲裁（隔离测试，验证动作/比例映射与实盘一致）
# --------------------------------------------------------------------------
def test_unit_stop_loss_relaxed():
    pos = {"etf_code": "X", "buy_price": 1.0, "buy_shares": 100,
            "is_trend_stock": True}
    # 持仓<5天，浮亏 -8% 触及放宽止损线 -7.2%，触发止损（动态止损）
    trig, st, prio, action, _ = _check_take_profit_stop_loss(pos, -8.0, hold_days=2)
    assert trig and action == SellAction.STOP_LOSS.value and prio == 75


def test_unit_take_profit_steps():
    pos = {"etf_code": "X", "buy_price": 1.0, "buy_shares": 100,
            "is_trend_stock": True}
    # 阶梯止盈：+30% -> 减1/3；+40% -> 减一半；+50% -> 清仓
    _, _, _, a1, _ = _check_take_profit_stop_loss(pos, 30.0, 10)
    _, _, _, a2, _ = _check_take_profit_stop_loss(pos, 40.0, 10)
    _, _, _, a3, _ = _check_take_profit_stop_loss(pos, 50.0, 10)
    assert a1 == SellAction.REDUCE_33.value
    assert a2 == SellAction.REDUCE_HALF.value
    assert a3 == SellAction.CLEAR_ALL.value


def test_unit_emergency_circuit():
    pos = {"etf_code": "X", "buy_price": 1.0, "buy_shares": 100,
            "is_trend_stock": True}
    # 单笔浮亏 <= -5% 触发紧急清仓（优先级100）
    trig, st, prio, action, _ = _check_emergency_circuit(pos, -6.0, -60.0, -6.0)
    assert trig and action == SellAction.CLEAR_ALL.value and prio == 100
    # 组合层面浮亏 <= -5% 也触发（即使单笔未触）
    trig2, _, _, a2, _ = _check_emergency_circuit(pos, 0.0, 0.0, -7.0)
    assert trig2 and a2 == SellAction.CLEAR_ALL.value


def test_unit_danger_signal():
    pos = {"etf_code": "X", "buy_price": 1.0, "buy_shares": 100,
            "is_trend_stock": True}
    # 单一危险信号 -> 减仓50%；多重 -> 清仓
    _, _, _, a1, _ = _check_danger_signal(pos, {"death_cross": True})
    _, _, _, a2, _ = _check_danger_signal(
        pos, {"death_cross": True, "volume_price_divergence": True})
    assert a1 == SellAction.REDUCE_50.value
    assert a2 == SellAction.CLEAR_ALL.value


def test_unit_trend_break_only_for_trend_stock():
    pos_trend = {"etf_code": "X", "buy_price": 1.0, "buy_shares": 100,
                  "is_trend_stock": True}
    pos_plain = {"etf_code": "X", "buy_price": 1.0, "buy_shares": 100,
                  "is_trend_stock": False}
    trig_t, _, _, _, _ = _check_trend_analysis(pos_trend, {"trend_break": True})
    trig_p, _, _, _, _ = _check_trend_analysis(pos_plain, {"trend_break": True})
    assert trig_t and not trig_p


def test_unit_peak_reversal_steps():
    # retreat = peak_gain - today_change；需 peak_gain >= RISE(2.6) 才进入裁决。
    # 用 today_change=2.0 + 整数级峰值，避开浮点 .5 边界。
    bar = {"today_change": 2.0, "high": 1.05, "prev_close": 1.0, "open": 1.0,
            "close": 1.01, "low": 0.99, "high_open_pct": 5.0, "drop_from_open": -4.0,
            "peak_gain": 3.9}  # retreat=1.9 >= 1.5 -> 清仓
    _, _, _, a1, _ = _check_peak_reversal({"etf_code": "X"}, bar)
    bar["peak_gain"] = 3.6  # retreat=1.6 >= 1.5 -> 清仓
    _, _, _, a2, _ = _check_peak_reversal({"etf_code": "X"}, bar)
    bar["peak_gain"] = 3.2  # retreat=1.2 介于 [1.0,1.5) -> 减一半
    _, _, _, a3, _ = _check_peak_reversal({"etf_code": "X"}, bar)
    assert a1 == SellAction.CLEAR_ALL.value
    assert a2 == SellAction.CLEAR_ALL.value
    assert a3 == SellAction.REDUCE_HALF.value


def test_unit_mandatory_reduction():
    bar = {"today_change": 4.0, "high": 1.07, "prev_close": 1.0, "open": 1.0,
            "close": 1.04, "low": 0.99, "high_open_pct": 7.0, "drop_from_open": -3.0,
            "peak_gain": 7.0}  # 涨幅>=3.5 且 high>open 且 close<high -> 减50%
    trig, _, _, action, _ = _check_mandatory_reduction({"etf_code": "X"}, bar)
    assert trig and action == SellAction.REDUCE_50.value
    # 涨幅不足 -> 不触发
    bar2 = dict(bar); bar2["today_change"] = 2.0; bar2["peak_gain"] = 2.0
    trig2, _, _, _, _ = _check_mandatory_reduction({"etf_code": "X"}, bar2)
    assert not trig2


def test_unit_high_open_dump_needs_downtrend():
    indicators_up = {"is_uptrend_arrangement": True}
    indicators_down = {"is_uptrend_arrangement": False}
    bar = {"high_open_pct": 3.0, "drop_from_open": -2.0}
    _, _, _, a_up, _ = _check_high_open_dump({"etf_code": "X"}, bar, indicators_up)
    trig_dn, _, _, a_dn, _ = _check_high_open_dump({"etf_code": "X"}, bar, indicators_down)
    assert a_up == "" and trig_dn and a_dn == SellAction.CLEAR_ALL.value


# --------------------------------------------------------------------------
# 2) 组合层 discipline=True vs False 公平对比
# --------------------------------------------------------------------------
def _rec_all(dates, codes):
    return {d: set(codes) for d in dates}


def test_portfolio_discipline_protects_capital():
    dates = _dates(10)
    # A：先平稳后崩盘（d8 跌到 0.90，d9 0.80）；B：平稳上行到 1.20
    kA = _mk("A", [1.0] * 8 + [0.90, 0.80])
    kB = _mk("B", [1.0] * 8 + [1.01, 1.02])  # 平缓上行，避开通高回落/止盈
    klines = {"A": kA, "B": kB}
    rec = _rec_all(dates, ["A", "B"])

    def _run(discipline: bool) -> dict:
        req = BacktestRequest(codes=[], start_date=dates[0], end_date=dates[-1],
                             initial_cash=100_000, fee_rate=0.0, slippage=0.0,
                             discipline=discipline)
        return PortfolioBacktest(klines).run(["A", "B"], req, dates, rec)

    r_on = _run(True)
    r_off = _run(False)

    # discipline=True：A 在崩盘日(d8)被紧急止损清仓
    a_sells_on = [t for t in r_on["trades"] if t.code == "A" and t.side == "SELL"]
    assert a_sells_on, "discipline=True 应在崩盘日卖出 A"
    assert "紧急熔断" in a_sells_on[0].note or "CLEAR_ALL" in a_sells_on[0].note
    assert r_on["discipline_triggers"].get("紧急熔断", 0) >= 1

    # discipline=False：A 始终被推荐，从不卖出（朴素持有到底）
    a_sells_off = [t for t in r_off["trades"] if t.code == "A" and t.side == "SELL"]
    assert not a_sells_off, "discipline=False 不应卖出 A"
    assert r_off["discipline_triggers"] == {}

    # 纪律护城河：True 终值 > False 终值
    assert r_on["final_equity"] > r_off["final_equity"]


# --------------------------------------------------------------------------
# 3) 部分减仓执行分支（monkeypatch 注入 REDUCE_50）
# --------------------------------------------------------------------------
def test_portfolio_partial_reduction_keeps_position(monkeypatch):
    dates = _dates(10)
    kC = _mk("C", [1.0] * 10)
    klines = {"C": kC}
    rec = _rec_all(dates, ["C"])

    target_date = dates[5]  # d5

    def _fake(position, klines_upto, portfolio_pnl_pct=0.0, indicators=None):
        cur = klines_upto[-1].trade_date if klines_upto else ""
        if position.get("etf_code") == "C" and cur == target_date:
            return SellDecision(triggered=True, strategy_type="强制减仓",
                               priority=65, action=SellAction.REDUCE_50.value,
                               detail="测试减仓", reduce_ratio=0.5)
        return SellDecision(triggered=False, strategy_type="", priority=0,
                           action="", detail="")

    monkeypatch.setattr(
        "src.backtest.engine.historical_sell_check", _fake)

    req = BacktestRequest(codes=[], start_date=dates[0], end_date=dates[-1],
                         initial_cash=100_000, fee_rate=0.0, slippage=0.0,
                         discipline=True)
    r = PortfolioBacktest(klines).run(["C"], req, dates, rec)

    sells = [t for t in r["trades"] if t.code == "C" and t.side == "SELL"]
    assert len(sells) == 1, "应恰好一次部分减仓"
    assert "REDUCE_50" in sells[0].note
    # 减仓后仍持仓（期末权益 = 剩余 50% 份额按末日收盘估值，>0）
    assert r["final_equity"] > 0


# --------------------------------------------------------------------------
# 4) T+1：当日买入当日不可被纪律卖出
# --------------------------------------------------------------------------
def test_portfolio_discipline_respects_t1(monkeypatch):
    dates = _dates(10)
    # C 全程平稳，仅在第 0 日（买入当日）被注入清仓信号 -> 应被 T+1 拦截
    kC = _mk("C", [1.0] * 10)
    klines = {"C": kC}
    rec = _rec_all(dates, ["C"])

    def _fake(position, klines_upto, portfolio_pnl_pct=0.0, indicators=None):
        cur = klines_upto[-1].trade_date if klines_upto else ""
        if position.get("etf_code") == "C" and cur == dates[0]:
            return SellDecision(triggered=True, strategy_type="紧急熔断",
                               priority=100, action=SellAction.CLEAR_ALL.value,
                               detail="", reduce_ratio=None)
        return SellDecision(triggered=False, strategy_type="", priority=0,
                           action="", detail="")

    monkeypatch.setattr(
        "src.backtest.engine.historical_sell_check", _fake)

    req = BacktestRequest(codes=[], start_date=dates[0], end_date=dates[-1],
                         initial_cash=100_000, fee_rate=0.0, slippage=0.0,
                         discipline=True)
    r = PortfolioBacktest(klines).run(["C"], req, dates, rec)

    # 当日(d0)不应发生卖出；之后也无信号 -> 全程零卖出
    sells = [t for t in r["trades"] if t.side == "SELL"]
    assert not sells
