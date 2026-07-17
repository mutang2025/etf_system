"""回测 API：POST /api/backtest/run（单标的 + 组合全市场）。

只读分析端点：不修改持仓 / 信号 / 数据库，仅重放历史 K 线产出业绩报告。

两种模式：
- mode="single"  （默认，向后兼容）
    逐标的回测；signal_source:
      - "momentum" : 内置动量信号
      - "screening" : 复用四层漏斗（ScreeningSignalSource），每只 code 独立建信号源
- mode="portfolio"  （组合层 / 全市场真实回测）
    一次性把宇宙（白名单 or 全市场）全部标的的历史 K 线落本地，
    逐交易日跑 **一遍** 四层漏斗拿到「当日推荐集合」，再模拟等权组合：
    新进推荐买入、掉出推荐卖出（守 T+1/手续费/滑点），基准=同宇宙等权买入持有。

数据抓取第一层：POST /api/backtest/fetch-history 可预先把宇宙历史落盘，
之后 run 只读本地、零网络消耗。
"""

from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.backtest.engine import (
    BacktestEngine,
    BacktestRequest,
    MomentumSignal,
    ScreeningSignalSource,
    run_portfolio_backtest,
)
from src.backtest.data_source import load_klines_from_store, ensure_history
from src.infrastructure.data_provider_factory import get_data_provider
from config import settings

router = APIRouter()


class BacktestRunReq(BaseModel):
    # 区间（两种模式都需要）
    start_date: str
    end_date: str
    initial_cash: float = 100_000.0
    fee_rate: float = 0.0003            # 单边万三
    slippage: float = 0.001             # 滑点
    # 单标的模式
    codes: list[str] = []
    signal_source: str = "momentum"      # 'momentum' | 'screening'
    momentum_window: int = 20
    momentum_buy: float = 0.05
    momentum_sell: float = -0.05
    # 组合模式
    mode: str = "single"                # 'single' | 'portfolio'
    universe: str = "whitelist"         # 'whitelist'（实盘选股宇宙 100 只）| 'full'（极慢）
    lookback_days: int = 250            # 默认回测 ~1 年（快）；可拉到 1200 看多年
    discipline: bool = True               # 组合回测：是否叠加实盘卖出纪律（止损/止盈/强制减仓）


class FetchHistoryReq(BaseModel):
    universe: str = "whitelist"         # 'whitelist' | 'full'
    lookback_days: int = 1200


def _resolve_universe(universe: str, provider) -> list[str]:
    """解析回测宇宙代码列表（带 .SH/.SZ 后缀）。"""
    pool = provider.get_etf_pool()
    if universe == "whitelist":
        # 白名单（config 中的 ETF_WHITELIST 已是 .SH/.SZ 后缀格式）
        wl = list(settings.ETF_WHITELIST)
        pool_codes = {e.code for e in pool}
        # 仅保留池中存在、且历史可落盘的标的
        return [c for c in wl if c in pool_codes]
    # full：全池 active / whitelist 状态
    return [e.code for e in pool
            if e.status in ("active", "whitelist")]


def _to_request(req: BacktestRunReq) -> BacktestRequest:
    return BacktestRequest(
        codes=req.codes,
        start_date=req.start_date,
        end_date=req.end_date,
        initial_cash=req.initial_cash,
        fee_rate=req.fee_rate,
        slippage=req.slippage,
        signal_source=req.signal_source,
        momentum_window=req.momentum_window,
        momentum_buy=req.momentum_buy,
        momentum_sell=req.momentum_sell,
        discipline=req.discipline,
    )


@router.post("/api/backtest/run")
def run_backtest(req: BacktestRunReq):
    if req.start_date > req.end_date:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")

    # ---------- 组合层 / 全市场真实回测 ----------
    if req.mode == "portfolio":
        provider = get_data_provider()
        universe = _resolve_universe(req.universe, provider)
        if not universe:
            raise HTTPException(
                status_code=400,
                detail="无法解析回测宇宙（白名单/全池为空，请先同步 ETF 池）",
            )
        # 1) 确保历史 K 线已落盘（缺的现拉，限频由 provider 内部保证）
        ensure_history(universe, req.lookback_days, provider)
        # 2) 读取本地全量历史（不触碰网络）
        klines = load_klines_from_store(universe)
        if not klines:
            raise HTTPException(
                status_code=400,
                detail="未找到历史K线缓存，请先调用 /api/backtest/fetch-history",
            )
        # 3) 组合层回测（复用四层漏斗作为信号源）
        pool = provider.get_etf_pool()
        result = run_portfolio_backtest(klines, pool, universe, _to_request(req))
        result["universe"] = req.universe
        result["signal_source"] = "screening"
        return result

    # ---------- 单标的回测（向后兼容） ----------
    if not req.codes:
        raise HTTPException(status_code=400, detail="codes 不能为空")
    klines = load_klines_from_store(req.codes)
    if not klines:
        raise HTTPException(
            status_code=400,
            detail="未找到给定代码的历史K线缓存，请先用真实数据源抓取并落盘",
        )

    breq = _to_request(req)
    results = []
    if req.signal_source == "screening":
        pool = get_data_provider().get_etf_pool()
        for code in req.codes:
            sig = ScreeningSignalSource(klines, pool, code)
            results.append(BacktestEngine(klines, sig).run_single(code, breq))
    else:
        sig = MomentumSignal(req.momentum_window, req.momentum_buy, req.momentum_sell)
        engine = BacktestEngine(klines, sig)
        for code in req.codes:
            results.append(engine.run_single(code, breq))

    return {
        "signal_source": req.signal_source,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "initial_cash": req.initial_cash,
        "results": [asdict(r) for r in results],
    }


@router.post("/api/backtest/fetch-history")
def fetch_history(req: FetchHistoryReq):
    """预拉取宇宙历史 K 线并落本地缓存（全市场回测前置步骤）。"""
    provider = get_data_provider()
    universe = _resolve_universe(req.universe, provider)
    if not universe:
        raise HTTPException(
            status_code=400,
            detail="无法解析回测宇宙（白名单/全池为空，请先同步 ETF 池）",
        )
    cached, failed, total = ensure_history(universe, req.lookback_days, provider)
    return {
        "universe": req.universe,
        "total": total,
        "cached": cached,
        "failed": failed,
    }
