"""组合层回测测试：模拟逻辑（买/卖/T+1/手续费滑点/基准/指标）、
推荐集合预计算、ensure_history 计数。

全程 mock，不触碰真实网络。PortfolioBacktest.run 直接喂手工编排的
rec_sets + K 线，隔离验证组合模拟；daily_recommended_sets 用桩引擎
验证「逐日跑一次漏斗」循环；ensure_history 用假 provider 验证计数。
"""

import math
import datetime as _dt

from src.backtest.engine import (
    PortfolioBacktest,
    BacktestRequest,
    daily_recommended_sets,
)
from src.domain.entities import DailyKline
from conftest import make_klines


def _req(**kw) -> BacktestRequest:
    return BacktestRequest(
        codes=kw.get("codes", []),
        start_date=kw.get("start_date", "2025-01-01"),
        end_date=kw.get("end_date", "2025-01-08"),
        initial_cash=kw.get("initial_cash", 100_000.0),
        fee_rate=kw.get("fee_rate", 0.001),
        slippage=kw.get("slippage", 0.001),
    )


def test_portfolio_buy_sell_t1_fees_benchmark():
    # A 上行、B 下行，构造确定性的买卖序列
    kA = make_klines(n=8, code="A", start=10.0, daily_return=+0.01)
    kB = make_klines(n=8, code="B", start=20.0, daily_return=-0.01)
    kbc = {"A": kA, "B": kB}
    dates = [k.trade_date for k in kA]

    # 推荐集合：A 进->A,B->仅B->清空->A->A->A->A->清空
    rec = {
        dates[0]: {"A"},
        dates[1]: {"A", "B"},
        dates[2]: {"B"},
        dates[3]: set(),
        dates[4]: {"A"},
        dates[5]: {"A"},
        dates[6]: {"A"},
        dates[7]: set(),
    }

    pb = PortfolioBacktest(kbc)
    res = pb.run(["A", "B"], _req(), dates, rec)

    # 交易次数 = 已平仓 SELL 数 = 3（A@2, B@3, A@7）
    assert res["trade_count"] == 3, res["trade_count"]
    # 总交易 = 3 买（A@0, B@1, A@4）+ 3 卖 = 6
    assert len(res["trades"]) == 6, len(res["trades"])

    # T+1：每笔 SELL 必有更早的同源 BUY（卖出晚于买入）
    sells = [t for t in res["trades"] if t.side == "SELL"]
    assert len(sells) == 3
    for s in sells:
        buys = [t for t in res["trades"]
                 if t.side == "BUY" and t.code == s.code and t.date < s.date]
        assert buys, f"SELL {s.code}@{s.date} 无更早 BUY（T+1 违例）"

    # 首日买入后权益 < 初始（现金被买入 + 手续费占用）
    assert res["equity_curve"][0][1] < 100_000.0

    # 基准曲线与权益曲线同日点数量一致
    assert len(res["benchmark_curve"]) == len(res["equity_curve"]) == 8

    # 指标合理：回撤 >= 0、Sharpe 有限、胜率 ∈ [0,1]
    assert res["max_drawdown_pct"] >= 0
    assert not math.isnan(res["sharpe"])
    assert 0.0 <= res["win_rate"] <= 1.0
    # A 两胜 B 一负 -> 胜率 2/3
    assert abs(res["win_rate"] - 2 / 3) < 0.01, res["win_rate"]

    # 期末权益有限且为正
    assert math.isfinite(res["final_equity"]) and res["final_equity"] > 0


def test_portfolio_empty_no_crash():
    kA = make_klines(n=4, code="A", start=10.0)
    pb = PortfolioBacktest({"A": kA})
    res = pb.run(["A"], _req(), [], {})
    assert res["trade_count"] == 0
    assert res["equity_curve"] == []
    assert res["benchmark_curve"] == []
    assert res["final_equity"] == 100_000.0


def test_daily_recommended_sets_loops_per_date(monkeypatch):
    # 桩引擎：按日期返回预设推荐集合，并记录被调用的日期
    dates = [f"2025-01-0{i+1}" for i in range(3)]  # 01,02,03
    klines = [DailyKline(etf_code="X", trade_date=d,
                          open=1, high=1, low=1, close=1, volume=1, amount=1)
               for d in dates]
    kbc = {"X": klines}
    pool = [type("E", (), {"code": "X"})()]

    rec_map = {dates[0]: {"X"}, dates[1]: set(), dates[2]: {"X"}}

    class Stub:
        def __init__(self, view):
            self.view = view
        def run_full_screening(self, d):
            rec = rec_map.get(d, set())
            return [type("R", (), {"etf_code": "X",
                                 "final_recommended": "X" in rec})()]

    # 桩打在 engine 模块的命名空间（engine 从 screening_engine import 了该名）
    monkeypatch.setattr("src.backtest.engine.ScreeningEngine", Stub)

    got_dates, got_sets = daily_recommended_sets(
        kbc, pool, "2025-01-01", "2025-01-03")
    assert got_dates == dates
    assert got_sets[dates[0]] == {"X"}
    assert got_sets[dates[1]] == set()
    assert got_sets[dates[2]] == {"X"}


def test_ensure_history_counts(monkeypatch):
    from src.backtest.data_source import ensure_history
    from src.domain.entities import DailyKline

    kl = [DailyKline(etf_code="A", trade_date="2025-01-01",
                      open=1, high=1, low=1, close=1, volume=1, amount=1)]
    prov = type("P", (), {
        "get_klines": lambda self, c, d: {"A": kl}.get(c, [])
    })()

    # 隔离：让 load_klines_from_store 永远返回空，强制走假 provider
    monkeypatch.setattr(
        "src.backtest.data_source.load_klines_from_store", lambda codes: {})

    cached, failed, total = ensure_history(["A", "B"], 250, prov)
    assert total == 2
    assert cached == 1   # A 有数据
    assert failed == 1   # B 无数据
