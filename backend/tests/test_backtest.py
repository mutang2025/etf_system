"""P3 回测框架骨架测试。

全程 mock 数据源 + 确定性 K 线，不触碰真实网络。
覆盖：
1. 动量信号买在上涨段、卖在下跌段
2. T+1：买入当天不可卖，次日方可平仓
3. 手续费 / 滑点从权益扣除
4. 指标合理（回撤>=0、Sharpe 有限、胜率 ∈ [0,1]）
5. 买入持有基准曲线生成
6. ScreeningSignalSource 复用四层漏斗产生信号（零复制）
7. POST /api/backtest/run 端点
"""

import math
from datetime import datetime, timedelta

from conftest import make_klines
from src.domain.entities import DailyKline, ETF
from src.backtest.engine import (
    BacktestEngine,
    BacktestRequest,
    MomentumSignal,
    ScreeningSignalSource,
)


# --------------------------------------------------------------------------
# 测试辅助：构造确定性 K 线
# --------------------------------------------------------------------------
def _prices() -> list:
    """先 flat 10 天，再涨 15 天，再跌 15 天（共 40 天）。"""
    p = [10.0] * 10
    cur = 10.0
    for _ in range(15):
        cur *= 1.01
        p.append(cur)
    for _ in range(15):
        cur *= 0.99
        p.append(cur)
    return p


def _klines(code: str = "510300.SH", prices: list = None,
            base: str = "2025-01-01") -> list:
    if prices is None:
        prices = _prices()
    kl = []
    d = datetime.strptime(base, "%Y-%m-%d")
    for i, pr in enumerate(prices):
        day = (d + timedelta(days=i)).strftime("%Y-%m-%d")
        kl.append(DailyKline(
            etf_code=code, trade_date=day,
            open=round(pr, 4), high=round(pr * 1.01, 4),
            low=round(pr * 0.99, 4), close=round(pr, 4),
            volume=1_000_000.0, amount=round(pr * 1e4, 2),
        ))
    return kl


# --------------------------------------------------------------------------
# 1. 动量信号买涨卖跌
# --------------------------------------------------------------------------
def test_momentum_buys_up_sells_down():
    kl = _klines()
    eng = BacktestEngine({"510300.SH": kl},
                         MomentumSignal(window=5, buy=0.03, sell=-0.03))
    res = eng.run_single("510300.SH", BacktestRequest(
        codes=["510300.SH"], start_date="2025-01-01", end_date="2025-12-31"))

    sides = [t.side for t in res.trades]
    assert "BUY" in sides and "SELL" in sides
    buy = [t for t in res.trades if t.side == "BUY"][0]
    sell = [t for t in res.trades if t.side == "SELL"][0]
    assert sell.date > buy.date


# --------------------------------------------------------------------------
# 2. T+1：买入当天不可卖，次日方可平仓
# --------------------------------------------------------------------------
class _ImmediateSellAfterBuy:
    """状态化信号源：首个可买日买入，之后任意持仓日卖出。"""

    def __init__(self):
        self.bought = False

    def signal(self, upto, pos_open):
        if not pos_open and not self.bought:
            self.bought = True
            return "BUY"
        if pos_open:
            self.bought = False
            return "SELL"
        return "HOLD"


def test_t_plus_one_blocks_same_day_sell():
    kl = _klines()
    eng = BacktestEngine({"X": kl}, _ImmediateSellAfterBuy())
    res = eng.run_single("X", BacktestRequest(
        codes=["X"], start_date="2025-01-01", end_date="2025-12-31"))

    buys = [t for t in res.trades if t.side == "BUY"]
    sells = [t for t in res.trades if t.side == "SELL"]
    assert buys and sells
    # 卖出必须发生在买入次日（T+1），而非买入当天
    assert sells[0].date > buys[0].date


# --------------------------------------------------------------------------
# 3. 手续费 / 滑点从权益扣除
# --------------------------------------------------------------------------
def test_fees_and_slippage_deducted():
    kl = _klines()
    eng = BacktestEngine({"510300.SH": kl},
                         MomentumSignal(window=5, buy=0.03, sell=-0.03))
    res = eng.run_single("510300.SH", BacktestRequest(
        codes=["510300.SH"], initial_cash=100_000.0,
        fee_rate=0.001, slippage=0.002,
        start_date="2025-01-01", end_date="2025-12-31"))

    buy = [t for t in res.trades if t.side == "BUY"][0]
    assert buy.fee > 0
    # 手续费 = 成交额 * 单边费率
    assert abs(buy.fee - buy.amount * 0.001) < 1e-2
    # 滑点使实际买入价高于当日收盘价（买入成本被抬高）
    buy_close = next(k.close for k in kl if k.trade_date == buy.date)
    assert buy.price > buy_close


# --------------------------------------------------------------------------
# 4. 指标合理
# --------------------------------------------------------------------------
def test_metrics_sane():
    kl = _klines()
    eng = BacktestEngine({"510300.SH": kl},
                         MomentumSignal(window=5, buy=0.03, sell=-0.03))
    res = eng.run_single("510300.SH", BacktestRequest(
        codes=["510300.SH"], start_date="2025-01-01", end_date="2025-12-31"))

    assert res.max_drawdown_pct >= 0
    assert math.isfinite(res.sharpe)        # 不为 nan / inf
    assert 0.0 <= res.win_rate <= 1.0
    sell_count = len([t for t in res.trades if t.side == "SELL"])
    assert res.trade_count == sell_count


# --------------------------------------------------------------------------
# 5. 买入持有基准曲线
# --------------------------------------------------------------------------
def test_buy_and_hold_benchmark():
    kl = _klines()
    eng = BacktestEngine({"510300.SH": kl},
                         MomentumSignal(window=5, buy=0.03, sell=-0.03))
    res = eng.run_single("510300.SH", BacktestRequest(
        codes=["510300.SH"], initial_cash=100_000.0,
        fee_rate=0.001, slippage=0.0,
        start_date="2025-01-01", end_date="2025-12-31"))

    assert len(res.benchmark_curve) == len(kl)
    first = res.benchmark_curve[0][1]
    # 期初全仓买入，落定市值 = initial - 买入手续费（< initial，且接近）
    assert 99_000.0 < first < 100_000.0


# --------------------------------------------------------------------------
# 6. ScreeningSignalSource 复用四层漏斗（零复制）
# --------------------------------------------------------------------------
def test_screening_signal_source_reuses_funnel():
    code = "510300.SH"
    # 严格上行 70 天 -> 多头排列、Layer4 无风险信号
    kl = make_klines(70, code, start=2.0, daily_return=0.01)
    etf = ETF(
        code=code, name="测试ETF", exchange="SH", etf_type="A股",
        theme="科技", status="active", total_market_cap=200.0,
        avg_amount_20d=5000.0, list_date="2020-01-01",
    )
    sig = ScreeningSignalSource({code: kl}, [etf], code)
    # 空仓 + 该 code 在历史视图上通过四层漏斗 -> 应被推荐 -> BUY
    assert sig.signal(kl, position_open=False) == "BUY"


# --------------------------------------------------------------------------
# 7. POST /api/backtest/run 端点
# --------------------------------------------------------------------------
def test_api_run_backtest(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import src.backtest.api as api

    kl = _klines()
    app = FastAPI()
    app.include_router(api.router)
    client = TestClient(app)

    # 绕过「从本地落盘缓存读历史」，直接注入确定性 K 线
    monkeypatch.setattr(api, "load_klines_from_store",
                        lambda codes: {"510300.SH": kl})

    r = client.post("/api/backtest/run", json={
        "codes": ["510300.SH"],
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "signal_source": "momentum",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["signal_source"] == "momentum"
    assert len(body["results"]) == 1
    assert "trades" in body["results"][0]
