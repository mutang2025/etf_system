"""回测引擎：在历史 K 线上重放信号、模拟撮合、统计业绩。

管道（单标的）：
  全量历史 K 线 -> 逐日切片 klines[:i+1] -> SignalSource.signal(window, position_open)
  -> 'BUY' / 'SELL' / 'HOLD' -> 撮合（手续费/滑点/T+1）-> 权益曲线
  -> 统计（累计收益/最大回撤/Sharpe/胜率）

撮合约定（贴近真实交易摩擦）：
- 手续费：单边 fee_rate，买卖各收一次
- 滑点：  买入价 *(1+slippage)，卖出价 *(1-slippage)
- T+1：    买入当日不可卖，次交易日方可平仓

信号源为可插拔接口（Protocol），默认 MomentumSignal 跑通管道；
四层漏斗以 ScreeningSignalSource 复用（见 signal_source 模块），
切换 signal_source="screening" 即可启用，不复制任何漏斗逻辑。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Protocol

import numpy as np

from src.domain.entities import DailyKline
from src.backtest.data_source import HistoricalViewProvider
from src.screening.screening_engine import ScreeningEngine
from src.backtest.sell_discipline import historical_sell_check, compute_history_indicators
from src.domain.enums import SellAction
from config import settings


# --------------------------------------------------------------------------
# 信号源接口
# --------------------------------------------------------------------------
class SignalSource(Protocol):
    """回测信号源：给定「截至今日的 K 线窗口」与当前是否持仓，返回动作。"""

    def signal(self, klines_upto: list[DailyKline], position_open: bool) -> str:
        """返回 'BUY' | 'SELL' | 'HOLD'。"""
        ...


# --------------------------------------------------------------------------
# 请求 / 结果数据结构
# --------------------------------------------------------------------------
@dataclass
class BacktestRequest:
    codes: list[str]
    start_date: str
    end_date: str
    initial_cash: float = 100_000.0
    fee_rate: float = 0.0003           # 单边手续费率（万三）
    slippage: float = 0.001            # 滑点（成交价 ±）
    signal_source: str = "momentum"     # 'momentum' | 'screening'
    discipline: bool = True              # 组合回测：是否叠加实盘卖出纪律
    # 动量信号参数
    momentum_window: int = 20
    momentum_buy: float = 0.05         # 窗口收益 >= 该值且空仓 -> 买入
    momentum_sell: float = -0.05       # 窗口收益 <= 该值且持仓 -> 卖出


@dataclass
class Trade:
    code: str
    side: str                   # 'BUY' | 'SELL'
    date: str
    price: float
    shares: float
    amount: float
    fee: float
    pnl: float = 0.0          # 仅 SELL 有意义（相对买入成本）
    note: str = ""              # 卖出来源标记：纪律策略/动作 或 空（掉出推荐集）


@dataclass
class BacktestResult:
    code: str
    initial_cash: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    win_rate: float
    trade_count: int
    equity_curve: list = field(default_factory=list)      # list[(date, equity)]
    benchmark_curve: list = field(default_factory=list)    # 买入持有基准
    trades: list = field(default_factory=list)


# --------------------------------------------------------------------------
# 内置信号源：动量（默认，跑通管道用）
# --------------------------------------------------------------------------
class MomentumSignal:
    """窗口动量信号：窗口内收益超阈值买入，跌破阈值卖出。"""

    def __init__(self, window: int = 20, buy: float = 0.05, sell: float = -0.05):
        self.window = window
        self.buy = buy
        self.sell = sell

    def signal(self, klines_upto: list[DailyKline], position_open: bool) -> str:
        if len(klines_upto) < self.window + 1:
            return "HOLD"
        window = klines_upto[-(self.window + 1):]
        ret = window[-1].close / window[0].close - 1
        if not position_open and ret >= self.buy:
            return "BUY"
        if position_open and ret <= self.sell:
            return "SELL"
        return "HOLD"


# --------------------------------------------------------------------------
# 内置信号源：复用四层漏斗（ScreeningEngine 在历史视图上运行）
# --------------------------------------------------------------------------
class ScreeningSignalSource:
    """把四层漏斗当信号源：每天在历史视图上跑 ScreeningEngine，
    若目标 code 被推荐（final_recommended）则 BUY，已持仓但不再被推荐则 SELL。

    零复制：直接 new ScreeningEngine(HistoricalViewProvider(...))，
    漏斗逻辑演进时回测自动跟随。仅绑定单标的（漏斗是选股，
    针对单标的回测要回答「这只是否被推荐」）。
    """

    def __init__(self, full_klines_by_code: dict, pool: list, code: str):
        self._full = full_klines_by_code
        self._pool = pool
        self._code = code

    def signal(self, klines_upto: list[DailyKline], position_open: bool) -> str:
        if not klines_upto:
            return "HOLD"
        cursor = klines_upto[-1].trade_date
        view = HistoricalViewProvider(self._full, cursor, self._pool)
        engine = ScreeningEngine(view)
        try:
            results = engine.run_full_screening(cursor)
        except Exception:
            # 漏斗任一环节在历史数据上异常时降级为 HOLD，不中断回测
            return "HOLD"
        rec = {r.etf_code: r for r in results}
        r = rec.get(self._code)
        if r is None:
            return "SELL" if position_open else "HOLD"
        if not position_open and r.final_recommended:
            return "BUY"
        if position_open and not r.final_recommended:
            return "SELL"
        return "HOLD"


# --------------------------------------------------------------------------
# 回测引擎
# --------------------------------------------------------------------------
class BacktestEngine:
    """对给定「全量历史 K 线」重放信号并模拟撮合。"""

    def __init__(self, klines_by_code: dict, signal_source: SignalSource):
        self.klines = klines_by_code
        self.signal = signal_source

    def run_single(self, code: str, req: BacktestRequest) -> BacktestResult:
        all_k = self.klines.get(code, [])
        klines = [k for k in all_k
                  if req.start_date <= k.trade_date <= req.end_date]
        if not klines:
            return self._empty(code, req)

        cash = float(req.initial_cash)
        shares = 0.0
        buy_price = 0.0
        buy_date: Optional[str] = None
        buy_fee = 0.0
        trades: list = []
        equity_curve: list = []

        for k in klines:
            pos_open = shares > 0
            sig = self.signal.signal(klines[:klines.index(k) + 1], pos_open)
            price = k.close

            if sig == "BUY" and shares == 0:
                fill = price * (1 + req.slippage)
                sh = cash / (fill * (1 + req.fee_rate))
                cost = sh * fill
                fee = cost * req.fee_rate
                cash -= (cost + fee)
                shares = sh
                buy_price = fill
                buy_date = k.trade_date
                buy_fee = fee
                trades.append(Trade(code, "BUY", k.trade_date,
                                     round(fill, 4), round(sh, 4),
                                     round(cost, 2), round(fee, 2)))

            elif sig == "SELL" and shares > 0 and buy_date != k.trade_date:
                # T+1：买入当日不可卖
                fill = price * (1 - req.slippage)
                proceeds = shares * fill
                fee = proceeds * req.fee_rate
                cash += (proceeds - fee)
                pnl = (fill - buy_price) * shares - fee - buy_fee
                trades.append(Trade(code, "SELL", k.trade_date,
                                     round(fill, 4), round(shares, 4),
                                     round(proceeds, 2), round(fee, 2),
                                     round(pnl, 2)))
                shares = 0.0
                buy_price = 0.0
                buy_date = None

            equity = cash + shares * price
            equity_curve.append((k.trade_date, round(equity, 2)))

        final_equity = cash + shares * klines[-1].close
        metrics = self._compute_metrics(equity_curve, trades, req.initial_cash)
        benchmark = self._buy_and_hold(klines, req.initial_cash, req.fee_rate, req.slippage)

        return BacktestResult(
            code=code,
            initial_cash=req.initial_cash,
            final_equity=round(final_equity, 2),
            total_return_pct=round((final_equity - req.initial_cash) / req.initial_cash * 100, 2),
            max_drawdown_pct=round(metrics["max_dd"] * 100, 2),
            sharpe=round(metrics["sharpe"], 3),
            win_rate=round(metrics["win_rate"], 4),
            trade_count=metrics["trade_count"],
            equity_curve=equity_curve,
            benchmark_curve=benchmark,
            trades=trades,
        )

    def _empty(self, code: str, req: BacktestRequest) -> BacktestResult:
        return BacktestResult(
            code=code,
            initial_cash=req.initial_cash,
            final_equity=req.initial_cash,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            sharpe=0.0,
            win_rate=0.0,
            trade_count=0,
        )

    @staticmethod
    def _compute_metrics(equity_curve: list, trades: list, initial: float) -> dict:
        eq = [e for _, e in equity_curve]
        if not eq:
            return {"max_dd": 0.0, "sharpe": 0.0, "win_rate": 0.0, "trade_count": 0}

        # 最大回撤
        peak = eq[0]
        max_dd = 0.0
        for e in eq:
            if e > peak:
                peak = e
            if peak > 0:
                dd = (peak - e) / peak
                if dd > max_dd:
                    max_dd = dd

        # Sharpe（年化，日收益）
        rets = []
        for i in range(1, len(eq)):
            if eq[i - 1] > 0:
                rets.append((eq[i] - eq[i - 1]) / eq[i - 1])
        sharpe = 0.0
        if len(rets) > 1:
            std = float(np.std(rets))
            if std > 0:
                sharpe = float(np.mean(rets)) / std * math.sqrt(252)

        # 胜率（基于已平仓 SELL 的 pnl）
        sells = [t for t in trades if t.side == "SELL"]
        wins = [t for t in sells if t.pnl > 0]
        win_rate = len(wins) / len(sells) if sells else 0.0

        return {
            "max_dd": max_dd,
            "sharpe": sharpe,
            "win_rate": win_rate,
            "trade_count": len(sells),
        }

    @staticmethod
    def _buy_and_hold(klines: list, initial: float, fee_rate: float, slippage: float) -> list:
        """基准：期初全仓买入并持有至期末（仅计买入手续费）。"""
        if not klines:
            return []
        price = klines[0].close * (1 + slippage)
        sh = initial / (price * (1 + fee_rate))
        return [(k.trade_date, round(sh * k.close, 2)) for k in klines]


# --------------------------------------------------------------------------
# 组合层回测（全市场 / 白名单宇宙）
# --------------------------------------------------------------------------
def _rec_cache_path(universe: list, start: str, end: str, version: str) -> str:
    """推荐集合缓存路径：key = 宇宙 + 起止 + 数据版本（数据刷新即失效）。"""
    import hashlib, os
    from config import settings
    key = "|".join(sorted(universe)) + f"|{start}|{end}|{version}"
    h = hashlib.md5(key.encode()).hexdigest()[:16]
    d = os.path.join(os.path.dirname(settings.DB_PATH), "backtest_cache")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"rec_{h}.json")


def _data_version(klines_by_code: dict) -> str:
    """数据版本：标的数 + 全市场最晚交易日（K 线刷新后自动变化）。"""
    latest = ""
    for kl in klines_by_code.values():
        for k in kl:
            if k.trade_date > latest:
                latest = k.trade_date
    return f"{len(klines_by_code)}|{latest}"


def _load_rec_cache(universe, start, end, version):
    import json
    p = _rec_cache_path(universe, start, end, version)
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data["dates"], {d: set(s) for d, s in data["sets"].items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_rec_cache(universe, start, end, version, dates, sets):
    import json
    p = _rec_cache_path(universe, start, end, version)
    data = {"dates": dates, "sets": {d: sorted(s) for d, s in sets.items()}}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f)


def daily_recommended_sets(klines_by_code: dict, pool: list,
                          start: str, end: str) -> tuple[list, dict]:
    """逐交易日跑一次四层漏斗，返回 (sorted_dates, {date: set(推荐code)})。

    关键：每天只跑 **一遍** 完整漏斗（而非逐标的各跑一遍），
    拿到当日「final_recommended」集合，组合层据此再平衡。
    数据来自全量历史切片的 HistoricalViewProvider，漏斗逻辑零复制、自动演进。
    任一交易日漏斗异常则降级为空集合，不中断整段回测。
    """
    all_dates: set = set()
    for kl in klines_by_code.values():
        for k in kl:
            if start <= k.trade_date <= end:
                all_dates.add(k.trade_date)
    dates = sorted(all_dates)
    out: dict = {}
    for d in dates:
        view = HistoricalViewProvider(klines_by_code, d, pool)
        try:
            results = ScreeningEngine(view).run_full_screening(d)
        except Exception:
            out[d] = set()
            continue
        out[d] = {r.etf_code for r in results
                   if getattr(r, "final_recommended", False)}
    return dates, out


def run_portfolio_backtest(klines_by_code: dict, pool: list,
                           universe_codes: list, req: "BacktestRequest") -> dict:
    """组合层回测顶层入口：复用四层漏斗作为信号源。

    流程：① 按 (宇宙, 起止, 数据版本) 取/存推荐集合缓存；
    ② 逐交易日模拟等权组合（新进推荐买入、掉出推荐卖出、
       买入当日 T+1 不可卖、手续费 + 滑点）；③ 统计 + 同宇宙等权基准。
    """
    version = _data_version(klines_by_code)
    cached = _load_rec_cache(universe_codes, req.start_date, req.end_date, version)
    if cached:
        rec_dates, rec_sets = cached
    else:
        rec_dates, rec_sets = daily_recommended_sets(
            klines_by_code, pool, req.start_date, req.end_date)
        _save_rec_cache(universe_codes, req.start_date, req.end_date,
                        version, rec_dates, rec_sets)

    if not rec_dates:
        return _empty_portfolio(req, universe_codes)

    pb = PortfolioBacktest(klines_by_code)
    return pb.run(universe_codes, req, rec_dates, rec_sets)


def _empty_portfolio(req: "BacktestRequest", universe_codes: list) -> dict:
    return {
        "mode": "portfolio",
        "universe": "",
        "universe_size": len(universe_codes),
        "active_days": 0,
        "discipline_enabled": bool(req.discipline),
        "discipline_triggers": {},
        "start_date": req.start_date,
        "end_date": req.end_date,
        "initial_cash": req.initial_cash,
        "final_equity": round(req.initial_cash, 2),
        "total_return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "sharpe": 0.0,
        "win_rate": 0.0,
        "trade_count": 0,
        "equity_curve": [],
        "benchmark_curve": [],
        "trades": [],
    }


class PortfolioBacktest:
    """组合模拟：在回测区间逐交易日重放四层漏斗推荐集合。

    策略（贴合实盘「跟随漏斗推荐篮」）：
    - 目标篮 = 当日 final_recommended 集合；
    - 持仓中掉出目标篮 → 卖出（T+1 当日不可卖）；
    - 目标篮中未持仓 → 用当前现金 **等权** 买入新进标的；
    - 已有的持仓不每日再平衡（避免无谓换手与手续费侵蚀）。
    """

    def __init__(self, klines_by_code: dict):
        self.klines = klines_by_code
        # 价格索引：{code: {date: close}}，权益估值 O(1)
        self._price = {
            c: {k.trade_date: k.close for k in kl}
            for c, kl in klines_by_code.items()
        }
        # 全量 K 线（按 code 索引），纪律检查需「截至当日」的窗口
        self._klines_by_code = klines_by_code
        # 指标缓存：{(code, date): indicators}，避免每持仓每日重算
        self._ind_cache: dict = {}

    def run(self, universe_codes: list, req: "BacktestRequest",
            rec_dates: list, rec_sets: dict) -> dict:
        # 仅保留有 K 线的宇宙标的
        universe = [c for c in universe_codes if c in self._price]
        if not universe or not rec_dates:
            return _empty_portfolio(req, universe_codes)

        cash = float(req.initial_cash)
        positions: dict = {}   # code -> {shares, buy_price, buy_date, buy_fee, cost}
        equity_curve: list = []
        trades: list = []
        discipline_triggers: dict = {}   # strategy_type -> count
        # 纪律全平后的冷却期：实盘卖出后 SELL_COOLDOWN_DAYS 内不回买同标的，
        # 防止「纪律止损 -> 仍在推荐集 -> 当日又买回」的回测失真。
        cooldown_until: dict = {}   # code -> 冷却解除的交易日索引

        for day_idx, d in enumerate(rec_dates):
            target = rec_sets.get(d, set())

            # 0) 组合层面浮亏（紧急熔断 P100 需要）
            portfolio_pnl_pct = 0.0
            if req.discipline and positions:
                total_cost = sum(p["cost"] for p in positions.values())
                if total_cost > 0:
                    total_val = cash + sum(
                        p["shares"] * self._price[c].get(d, p["buy_price"])
                        for c, p in positions.items())
                    portfolio_pnl_pct = (total_val / total_cost - 1) * 100

            # 1) 实盘卖出纪律（可选）：止盈/止损/强制减仓/危险信号/趋势破位/高开砸盘/紧急熔断
            #    在「掉出推荐集」之前优先执行，体现「纪律护城河」。
            if req.discipline:
                for code in list(positions):
                    pos = positions[code]
                    if pos["buy_date"] == d:
                        continue            # T+1：当日买入不可卖
                    close = self._price[code].get(d)
                    if close is None:
                        continue
                    window = self._window(code, d)
                    indicators = self._indicators(code, d, window)
                    hold_days = (rec_dates.index(d)
                                 - rec_dates.index(pos["buy_date"]))
                    posdict = {
                        "etf_code": code,
                        "buy_price": pos["buy_price"],
                        "buy_shares": pos["shares"],
                        "buy_date": pos["buy_date"],
                        "hold_days": hold_days,
                        "is_trend_stock": indicators.get("is_trend_stock", False),
                        "current_price": close,
                    }
                    dec = historical_sell_check(
                        posdict, window, portfolio_pnl_pct, indicators)
                    if not dec.triggered:
                        continue
                    discipline_triggers[dec.strategy_type] = \
                        discipline_triggers.get(dec.strategy_type, 0) + 1
                    # 全平动作（清仓 / 止损）→ 整仓卖出
                    if dec.reduce_ratio is None:
                        fill = close * (1 - req.slippage)
                        proceeds = pos["shares"] * fill
                        fee = proceeds * req.fee_rate
                        cash += proceeds - fee
                        pnl = ((fill - pos["buy_price"]) * pos["shares"]
                                - fee - pos["buy_fee"])
                        trades.append(Trade(code, "SELL", d, round(fill, 4),
                                         round(pos["shares"], 4),
                                         round(proceeds, 2), round(fee, 2),
                                         round(pnl, 2),
                                         f"{dec.strategy_type}/{dec.action}"))
                        del positions[code]
                        # 纪律全平后进入冷却期（实盘卖出冷却，防当日回买）
                        cooldown_until[code] = day_idx + settings.SELL_COOLDOWN_DAYS
                    else:
                        # 部分减仓：按比例减少份额，保留持仓，结算已实现盈亏
                        ratio = dec.reduce_ratio
                        sell_shares = pos["shares"] * ratio
                        fill = close * (1 - req.slippage)
                        proceeds = sell_shares * fill
                        fee = proceeds * req.fee_rate
                        cash += proceeds - fee
                        pnl = (fill - pos["buy_price"]) * sell_shares - fee
                        pos["shares"] -= sell_shares
                        pos["cost"] -= pos["cost"] * ratio
                        trades.append(Trade(code, "SELL", d, round(fill, 4),
                                         round(sell_shares, 4),
                                         round(proceeds, 2), round(fee, 2),
                                         round(pnl, 2),
                                         f"{dec.strategy_type}/{dec.action}"))

            # 2) 卖出：持仓且不在目标篮（纪律未清的，掉出推荐集才卖）
            for code in list(positions):
                if code in target:
                    continue
                pos = positions[code]
                if pos["buy_date"] == d:
                    continue
                close = self._price[code].get(d)
                if close is None:
                    continue
                fill = close * (1 - req.slippage)
                proceeds = pos["shares"] * fill
                fee = proceeds * req.fee_rate
                cash += proceeds - fee
                pnl = (fill - pos["buy_price"]) * pos["shares"] - fee - pos["buy_fee"]
                trades.append(Trade(code, "SELL", d, round(fill, 4),
                                     round(pos["shares"], 4), round(proceeds, 2),
                                     round(fee, 2), round(pnl, 2)))
                del positions[code]

            # 3) 买入：目标篮中未持仓（且不在纪律冷却期），用当前现金等权分配
            entries = [c for c in target
                       if (c not in positions
                           and c in self._price
                           and cooldown_until.get(c, -1) <= day_idx)]
            if entries and cash > 1e-6:
                per = cash / len(entries)
                for code in entries:
                    close = self._price[code].get(d)
                    if close is None:
                        continue
                    fill = close * (1 + req.slippage)
                    if fill <= 0:
                        continue
                    sh = per / (fill * (1 + req.fee_rate))
                    if sh <= 0:
                        continue
                    cost = sh * fill
                    fee = cost * req.fee_rate
                    if cost + fee > cash:
                        # 资金不足：按剩余现金买入该标的
                        avail = cash
                        if avail <= 0:
                            break
                        sh = avail / (fill * (1 + req.fee_rate))
                        cost = sh * fill
                        fee = cost * req.fee_rate
                    cash -= (cost + fee)
                    positions[code] = {
                        "shares": sh, "buy_price": fill,
                        "buy_date": d, "buy_fee": fee, "cost": cost + fee,
                    }
                    trades.append(Trade(code, "BUY", d, round(fill, 4),
                                     round(sh, 4), round(cost, 2), round(fee, 2)))

            # 4) 权益估值
            eq = cash
            for code, pos in positions.items():
                eq += pos["shares"] * self._price[code].get(d, pos["buy_price"])
            equity_curve.append((d, round(eq, 2)))

        # 期末权益（持仓按最后一日收盘估值）
        final_date = rec_dates[-1]
        final_equity = cash
        for code, pos in positions.items():
            final_equity += pos["shares"] * self._price[code].get(final_date, pos["buy_price"])

        benchmark = self._benchmark_equal_weight(universe, req, rec_dates)
        metrics = BacktestEngine._compute_metrics(equity_curve, trades, req.initial_cash)

        return {
            "mode": "portfolio",
            "universe_size": len(universe),
            "active_days": len(rec_dates),
            "discipline_enabled": bool(req.discipline),
            "discipline_triggers": discipline_triggers,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "initial_cash": req.initial_cash,
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(
                (final_equity - req.initial_cash) / req.initial_cash * 100, 2),
            "max_drawdown_pct": round(metrics["max_dd"] * 100, 2),
            "sharpe": round(metrics["sharpe"], 3),
            "win_rate": round(metrics["win_rate"], 4),
            "trade_count": metrics["trade_count"],
            "equity_curve": equity_curve,
            "benchmark_curve": benchmark,
            "trades": trades,
        }

    # 历史窗口 / 指标缓存（纪律环节复用，避免每持仓每日重算）
    def _window(self, code: str, d: str) -> list:
        kl = self._klines_by_code.get(code, [])
        return [k for k in kl if k.trade_date <= d]

    def _indicators(self, code: str, d: str, window: Optional[list] = None) -> dict:
        key = (code, d)
        if key in self._ind_cache:
            return self._ind_cache[key]
        w = window if window is not None else self._window(code, d)
        ind = compute_history_indicators(w)
        self._ind_cache[key] = ind
        return ind

    def _benchmark_equal_weight(self, universe: list,
                                req: "BacktestRequest", rec_dates: list) -> list:
        """基准：期初等权买入全宇宙并持有至期末（仅计买入手续费）。"""
        first = rec_dates[0]
        bought = [c for c in universe if self._price[c].get(first) is not None]
        if not bought:
            return []
        per = req.initial_cash / len(bought)
        hold = {}
        for c in bought:
            close = self._price[c][first]
            fill = close * (1 + req.slippage)
            if fill <= 0:
                continue
            sh = per / (fill * (1 + req.fee_rate))
            hold[c] = (sh, fill)
        return [
            (d, round(sum(sh * self._price[c].get(d, fill)
                        for c, (sh, fill) in hold.items()), 2))
            for d in rec_dates
        ]
