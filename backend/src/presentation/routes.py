"""REST API routes for the ETF trading system."""

import asyncio
import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from src.infrastructure.database_repo import DatabaseRepository
from src.infrastructure.data_provider_factory import get_data_provider
from src.infrastructure.market_indices import get_index_provider
from src.screening.screening_engine import ScreeningEngine, get_screening
from src.trading.buy_signal import BuySignalEngine
from src.trading.position_manager import PositionManager
from src.trading.scan_tasks import run_buy_scan, run_sell_scan
from src.realtime_scanner import get_scanner
from src.presentation.security import require_auth
from src.infrastructure.indicator_cache import get_indicator_cache
from src.infrastructure.timeutil import now_cst
from src.domain.enums import parse_reduce_ratio
from config import settings

# 全局鉴权依赖：API_TOKEN 为空时为 no-op（本地开发）；设置后对全路由生效（P1-3）。
router = APIRouter(dependencies=[Depends(require_auth)])

# Initialize services lazily
_db: Optional[DatabaseRepository] = None
_buy_engine: Optional[BuySignalEngine] = None
_pos_manager: Optional[PositionManager] = None


def get_db() -> DatabaseRepository:
    global _db
    if _db is None:
        _db = DatabaseRepository()
        _db.init_default_params()
        # 启动即把库内策略参数加载进内存 config.settings，使引擎读取用户调优值（修 P0-1）
        _db.load_params_into_settings()
    return _db


def get_buy_engine() -> BuySignalEngine:
    global _buy_engine
    if _buy_engine is None:
        _buy_engine = BuySignalEngine()
    return _buy_engine


def get_pos_manager() -> PositionManager:
    global _pos_manager
    if _pos_manager is None:
        _pos_manager = PositionManager(get_db())
    return _pos_manager


# ============ Models ============

class ETFStatusUpdate(BaseModel):
    status: str  # active / blacklist / whitelist / excluded


class PoolBuyRequest(BaseModel):
    amount: Optional[float] = None  # 买入金额，缺省用单笔仓位上限

class BuyConfirmRequest(BaseModel):
    etf_code: str
    etf_name: str
    buy_price: float
    buy_amount: float

class SellConfirmRequest(BaseModel):
    position_id: int
    sell_price: float
    sell_strategy: str = "manual"
    sell_action: Optional[str] = None  # 减仓动作（REDUCE_*）；为空则按清仓处理

class AutoTradeRequest(BaseModel):
    buy: Optional[bool] = None   # 买入信号自动确认建仓
    sell: Optional[bool] = None  # 卖出信号自动执行（清仓/减仓）

class ParamUpdateRequest(BaseModel):
    key: str
    value: str
    group: str
    description: str = ""

class PresetApplyRequest(BaseModel):
    preset: str  # conservative / standard / aggressive


# ============ Dashboard ============

@router.get("/api/dashboard")
async def get_dashboard():
    """Get dashboard overview: portfolio summary, today signals, market status."""
    db = get_db()
    pos_manager = get_pos_manager()
    screening = get_screening()
    mock = get_data_provider()

    # Portfolio summary
    portfolio = pos_manager.get_portfolio_summary()

    # Today signals
    today = now_cst().strftime("%Y-%m-%d")
    signals = db.get_signals(limit=20)
    buy_signals = [s for s in signals if s["signal_type"] == "buy"]
    sell_signals = [s for s in signals if s["signal_type"] == "sell"]

    # Market status
    hs300_change = mock.get_hs300_today_change()
    is_empty, empty_reason = screening.check_market_empty_signal()

    # Performance
    perf = db.get_performance_stats()

    # Pool stats
    pool = db.get_etf_pool(status="active")

    return {
        "portfolio": portfolio,
        "signals": {
            "buy_count": len(buy_signals),
            "sell_count": len(sell_signals),
            "recent": signals[:5],
        },
        "market": {
            "hs300_change": hs300_change,
            "is_empty_signal": is_empty,
            "empty_reason": empty_reason,
            "is_trading_day": now_cst().weekday() < 5,
        },
        "performance": perf,
        "pool": {
            "total": len(pool),
            "active": len([e for e in pool if e["status"] == "active"]),
        },
    }


# ============ ETF Pool ============

@router.get("/api/etf-pool")
async def get_etf_pool(
    status: Optional[str] = Query(None),
    etf_type: Optional[str] = Query(None),
    code: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    theme: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None, description="排序字段，如 change_pct / avg_amount_20d / total_market_cap"),
    order: str = Query("desc", description="asc 升序 / desc 降序"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """Get ETF pool with filters.

    status   - exact (active/excluded/blacklist/whitelist)
    etf_type - exact (A股/跨境)
    code     - partial match
    name     - partial match
    theme    - exact match
    sort_by  - sort field (e.g. change_pct)
    order    - asc / desc
    """
    db = get_db()
    etfs = db.get_etf_pool(status=status, etf_type=etf_type, code=code, name=name,
                            theme=theme, sort_by=sort_by, order=order)
    total = len(etfs)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "data": etfs[start:end],
    }


@router.get("/api/etf-pool/themes")
async def get_etf_themes():
    """Get distinct themes for the filter dropdown."""
    db = get_db()
    return {"themes": db.get_etf_themes()}

@router.get("/api/etf-pool/{code}")
async def get_etf_detail(code: str, days: int = Query(30, ge=5, le=250)):
    """Get single ETF detail with K-line data."""
    db = get_db()
    mock = get_data_provider()
    etf = db.get_etf(code)
    if not etf:
        raise HTTPException(404, "ETF not found")
    # Try DB first, fallback to provider (K-lines not synced for all ETFs with AKShare)
    klines = db.get_klines_from_db(code, days)
    if not klines:
        # Fetch from provider on demand
        provider_klines = mock.get_klines(code, days)
        klines = [{"etf_code": k.etf_code, "trade_date": k.trade_date,
                   "open": k.open, "high": k.high, "low": k.low,
                   "close": k.close, "volume": k.volume, "amount": k.amount}
                  for k in provider_klines]
    rt = mock.get_realtime_quote(code)
    return {"etf": etf, "klines": klines[-days:], "realtime": rt}

@router.put("/api/etf-pool/{code}/status")
async def update_etf_status(code: str, body: ETFStatusUpdate):
    """Update ETF status (blacklist/whitelist/active/excluded)."""
    db = get_db()
    success = db.update_etf_status(code, body.status)
    if not success:
        raise HTTPException(404, "ETF not found")
    return {"code": code, "status": body.status, "message": f"ETF状态已更新为{body.status}"}

@router.post("/api/etf-pool/sync")
async def sync_etf_pool():
    """Manually trigger ETF pool sync."""
    db = get_db()
    result = db.sync_etf_pool()
    return {"message": "ETF池同步完成", **result}

@router.get("/api/etf-pool/sync-logs")
async def get_sync_logs():
    """Get pool sync history."""
    db = get_db()
    logs = db.get_pool_sync_logs()
    return {"data": logs}


# ============ Screening ============

@router.post("/api/screening/run")
async def run_screening():
    """Run the four-layer screening pipeline."""
    screening = get_screening()
    mock = get_data_provider()
    db = get_db()

    # Check empty signal
    is_empty, reason = screening.check_market_empty_signal()

    results = screening.run_full_screening()

    summary = screening.get_screening_summary(results)

    # Save results to DB
    # 同一日期重跑时先清空旧记录，避免旧推荐 ETF 残留导致刷新后出现多余结果
    db.clear_selection_results(summary["select_date"])
    for r in results:
        result_dict = {
            "select_date": r.select_date,
            "etf_code": r.etf_code,
            "etf_name": r.etf_name,
            "layer1_passed": bool(r.layer1_passed),
            "layer2_score": float(r.layer2_score),
            "layer2_rank": int(r.layer2_rank),
            "factor_scores": [{"factor_name": f.factor_name, "raw_value": float(f.raw_value),
                               "z_score": float(f.z_score), "weight": float(f.weight)} for f in r.factor_scores],
            "layer3_theme": r.layer3_theme,
            "layer3_theme_rank": int(r.layer3_theme_rank),
            "layer3_passed": bool(r.layer3_passed),
            "layer4_death_cross": bool(r.layer4_death_cross),
            "layer4_vol_price_div": bool(r.layer4_vol_price_div),
            "layer4_adx_danger": bool(r.layer4_adx_danger),
            "layer4_bb_risk": bool(r.layer4_bb_risk),
            "layer4_passed": bool(r.layer4_passed),
            "final_recommended": bool(r.final_recommended),
        }
        db.save_selection_result(result_dict)

    # 持久化完整漏斗快照，保证「进入页面读取最新一次」与「点击运行选股」
    # 两条路径展示的漏斗完全一致（run_full_screening 只把 layer3+ 子集入库）
    db.save_screening_run(summary["select_date"], summary["funnel"])

    # 手动重跑选股后使当日推荐缓存失效，下一轮买入扫描将取到最新结果
    screening.invalidate_cache()

    # 今日最终推荐 ETF 自动纳入待买入池（按实时价记录入池点位）
    # add_to_pool 会自动跳过已存在项（含已卖出的黑名单），避免重复入池
    recommendations = [r for r in results if r.final_recommended]
    pool_added, pool_skipped = 0, 0
    for r in recommendations:
        rt = mock.get_realtime_quote(r.etf_code)
        entry_price = rt["price"] if rt else 0.0
        if entry_price <= 0:
            pool_skipped += 1
            continue
        ok = db.add_to_pool(
            r.etf_code, r.etf_name, entry_price,
            now_cst().strftime("%Y-%m-%d %H:%M:%S"),
            score=float(r.layer2_score),
        )
        if ok:
            pool_added += 1
        else:
            pool_skipped += 1

    # 市场空仓状态仅通过返回体的 is_empty_signal / empty_reason 透传给
    # 选股页/仪表盘实时展示，不再作为一条「信号」写入 signals 表——
    # 否则信号中心会堆满无意义的「空仓」卡片，淹没真正的买卖信号。

    # Serialize results
    data = []
    for r in results:
        data.append({
            "etf_code": r.etf_code,
            "etf_name": r.etf_name,
            "layer1_passed": bool(r.layer1_passed),
            "layer2_score": float(r.layer2_score),
            "layer2_rank": int(r.layer2_rank),
            "factor_scores": [{"factor_name": f.factor_name, "raw_value": float(f.raw_value),
                               "z_score": float(f.z_score), "weight": float(f.weight)} for f in r.factor_scores],
            "layer3_theme": r.layer3_theme,
            "layer3_theme_rank": int(r.layer3_theme_rank),
            "layer3_passed": bool(r.layer3_passed),
            "layer4_death_cross": bool(r.layer4_death_cross),
            "layer4_vol_price_div": bool(r.layer4_vol_price_div),
            "layer4_adx_danger": bool(r.layer4_adx_danger),
            "layer4_bb_risk": bool(r.layer4_bb_risk),
            "layer4_passed": bool(r.layer4_passed),
            "final_recommended": bool(r.final_recommended),
        })

    return {
        "summary": summary,
        "is_empty_signal": is_empty,
        "empty_reason": reason if is_empty else "",
        "recommendations": [d for d in data if d["final_recommended"]],
        "all_results": data,
        "pool_added": pool_added,
        "pool_skipped": pool_skipped,
    }

@router.get("/api/screening/results")
async def get_screening_results(select_date: Optional[str] = None):
    """Get the latest saved screening results (default: today, else most recent run).

    Returns the SAME shape as POST /api/screening/run so the frontend can render
    the stored "latest run" identically to a fresh run:
        { summary, is_empty_signal, empty_reason, recommendations, all_results }
    """
    screening = get_screening()
    db = get_db()
    date = select_date or now_cst().strftime("%Y-%m-%d")
    rows = db.get_selection_results(date)

    # 默认（未指定日期）且今天还没跑过 -> 回退到"最近一次有结果的日期"，
    # 保证进入页面即展示最新一次选股结果（而非空白）。
    if not rows and select_date is None:
        latest = db.conn.execute(
            "SELECT select_date FROM selection_results "
            "GROUP BY select_date ORDER BY select_date DESC LIMIT 1"
        ).fetchone()
        if latest:
            date = latest["select_date"]
            rows = db.get_selection_results(date)

    # 优先用持久化的完整漏斗快照（与点击运行选股完全一致）；
    # 没有快照时退化为从入库行反推（仅 layer3+ 子集，宽度偏小）。
    run_snapshot = db.get_screening_run(date)
    funnel = None
    if run_snapshot:
        funnel = {
            "pool_total": run_snapshot["pool_total"],
            "layer1": run_snapshot["layer1"],
            "layer2": run_snapshot["layer2"],
            "layer3": run_snapshot["layer3"],
            "layer4": run_snapshot["layer4"],
            "final": run_snapshot["final"],
        }

    # 把 DB 行转成与 run_screening 完全一致的前端结构
    # （factor_scores 由 layer2_factor_details 的 JSON 字符串解析得到）
    all_results = []
    for r in rows:
        try:
            factor_scores = json.loads(r.get("layer2_factor_details") or "[]")
        except Exception:
            factor_scores = []
        all_results.append({
            "etf_code": r["etf_code"],
            "etf_name": r["etf_name"],
            "layer1_passed": bool(r["layer1_passed"]),
            "layer2_score": float(r["layer2_score"]),
            "layer2_rank": int(r["layer2_rank"]),
            "factor_scores": factor_scores,
            "layer3_theme": r.get("layer3_theme"),
            "layer3_theme_rank": int(r.get("layer3_theme_rank") or 0),
            "layer3_passed": bool(r["layer3_passed"]),
            "layer4_death_cross": bool(r["layer4_death_cross"]),
            "layer4_vol_price_div": bool(r["layer4_vol_price_div"]),
            "layer4_adx_danger": bool(r["layer4_adx_danger"]),
            "layer4_bb_risk": bool(r["layer4_bb_risk"]),
            "layer4_passed": bool(r["layer4_passed"]),
            "final_recommended": bool(r["final_recommended"]),
        })

    # 从实际存储结果自算漏斗（run_screening 在跑的过程中设置 _pipeline_counts，
    # 此处读取路径没有，故直接按行统计，仅作「无快照」时的退化兜底。
    if funnel is None:
        funnel = {
            "pool_total": len(screening.mock.get_etf_pool()),
            "layer1": sum(1 for r in all_results if r["layer1_passed"]),
            "layer2": sum(1 for r in all_results if r["layer2_rank"] > 0),
            "layer3": sum(1 for r in all_results if r["layer3_passed"]),
            "layer4": sum(1 for r in all_results if r["layer4_passed"]),
            "final": sum(1 for r in all_results if r["final_recommended"]),
        }
    summary = {
        "select_date": date,
        "layer1_passed": funnel["layer1"],
        "layer2_scored": funnel["layer2"],
        "layer3_clustered": funnel["layer3"],
        "layer4_passed": funnel["layer4"],
        "final_recommended": funnel["final"],
        "funnel": funnel,
    }

    is_empty, reason = screening.check_market_empty_signal()
    recommendations = [r for r in all_results if r["final_recommended"]]

    return {
        "summary": summary,
        "is_empty_signal": is_empty,
        "empty_reason": reason if is_empty else "",
        "recommendations": recommendations,
        "all_results": all_results,
    }


# ============ Signals ============

@router.get("/api/signals")
async def get_signals(
    signal_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
):
    """Get signals with optional filters."""
    db = get_db()
    signals = db.get_signals(signal_type=signal_type, status=status, limit=limit)
    return {"data": signals, "total": len(signals)}

@router.post("/api/signals/buy/scan")
async def scan_buy_signals():
    """Scan candidate ETFs for buy signal conditions (manual trigger)."""
    screening = get_screening()
    buy_engine = get_buy_engine()
    db = get_db()
    pos_manager = get_pos_manager()

    # 手动触发时先检查当日推荐是否已缓存；缓存为空则强制重跑一次
    result = run_buy_scan(screening, buy_engine, pos_manager, db)
    return result

@router.post("/api/signals/{signal_id}/confirm")
async def confirm_buy_signal(signal_id: str, body: BuyConfirmRequest):
    """Confirm a buy signal and create a position."""
    db = get_db()
    pos_manager = get_pos_manager()

    # 建仓（含重复开仓 / 超额校验，统一在 transaction 内完成）
    try:
        position = pos_manager.confirm_buy(
            signal_id=signal_id,
            etf_code=body.etf_code,
            etf_name=body.etf_name,
            buy_price=body.buy_price,
            buy_amount=body.buy_amount,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # 若已在待买入池，确认买入后同步移出（避免重复）
    db.remove_from_pool(body.etf_code)
    return {"message": "买入确认成功", "position": position}

@router.post("/api/signals/{signal_id}/skip")
async def skip_signal(signal_id: str):
    """Skip a signal."""
    db = get_db()
    db.update_signal_status(signal_id, "skipped")
    return {"message": "信号已跳过", "signal_id": signal_id}

@router.post("/api/signals/sell/scan")
async def scan_sell_signals():
    """Scan all holding positions for sell signal conditions (manual trigger)."""
    pos_manager = get_pos_manager()
    return run_sell_scan(pos_manager)


# ============ Auto-Trade (自动交易开关) ============

@router.get("/api/auto-trade")
async def get_auto_trade():
    """获取自动交易开关状态（买入/卖出信号是否触发即自动成交）。"""
    return {"buy": settings.AUTO_EXECUTE_BUY, "sell": settings.AUTO_EXECUTE_SELL}


@router.post("/api/auto-trade")
async def set_auto_trade(body: AutoTradeRequest):
    """实时切换自动交易开关。写入 strategy_params(auto 组) 并同步进 settings 单例，
    守护进程下一轮扫描即生效，无需重启。"""
    db = get_db()
    if body.buy is not None:
        db.set_param("auto_execute_buy", "true" if body.buy else "false",
                     "auto", "买入信号自动确认建仓")
    if body.sell is not None:
        db.set_param("auto_execute_sell", "true" if body.sell else "false",
                     "auto", "卖出信号自动执行（清仓/减仓）")
    return {"buy": settings.AUTO_EXECUTE_BUY, "sell": settings.AUTO_EXECUTE_SELL}


# ============ Pending Buy Pool ============
@router.get("/api/pending-pool")
async def get_pending_pool(status: Optional[str] = Query(None)):
    """待买入池列表（自动富集实时价/当日涨跌幅）。status=watching|sold 可筛选。"""
    db = get_db()
    mock = get_data_provider()
    items = db.get_pending_pool(status)
    for it in items:
        rt = mock.get_realtime_quote(it["etf_code"])
        it["current_price"] = rt["price"] if rt else None
        it["change_pct"] = rt["change_pct"] if rt else None
    return {"data": items, "total": len(items)}


@router.post("/api/pending-pool/{etf_code}/buy")
async def buy_from_pool(etf_code: str, body: Optional[PoolBuyRequest] = None):
    """从待买入池买入：建仓（成交价=实时价）并自动移出池子。"""
    db = get_db()
    pos_manager = get_pos_manager()
    item = db.get_pool_row(etf_code)
    if not item or item["status"] != "watching":
        raise HTTPException(status_code=404, detail="待买入池中无该可买项")
    rt = get_data_provider().get_realtime_quote(etf_code)
    buy_price = rt["price"] if rt else item["entry_price"]
    # 缺额回退为受总仓位上限约束的建议金额（修复 P1-1）
    buy_amount = (body.amount if body and body.amount
                  else pos_manager.suggested_buy_amount())
    signal_id = f"PBUY-{now_cst().strftime('%Y%m%d')}-{etf_code[-6:]}"
    try:
        pos_manager.confirm_buy(
            signal_id=signal_id, etf_code=etf_code, etf_name=item["etf_name"],
            buy_price=buy_price, buy_amount=buy_amount,
        )
    except ValueError as e:
        # 防重复开仓（P1-2）：持仓中再买同 ETF 应 409 而非 500
        raise HTTPException(status_code=409, detail=str(e))
    db.remove_from_pool(etf_code)
    return {"message": "已从待买入池买入并建仓", "etf_code": etf_code,
            "buy_price": buy_price, "buy_amount": round(buy_amount, 2)}


@router.post("/api/pending-pool/{etf_code}/remove")
async def remove_from_pool(etf_code: str):
    """人工移出待买入池（watching 或 sold 均可）。"""
    db = get_db()
    ok = db.remove_from_pool(etf_code)
    if not ok:
        raise HTTPException(status_code=404, detail="待买入池中无该项")
    return {"message": "已移出待买入池", "etf_code": etf_code}


# ============ Positions ============

@router.get("/api/positions")
async def get_positions(status: Optional[str] = Query(None)):
    """Get positions with optional status filter."""
    pos_manager = get_pos_manager()
    if status == "holding":
        positions = pos_manager.update_all_positions()
    else:
        positions = pos_manager.db.get_positions(status=status)
    return {"data": positions, "total": len(positions)}

@router.get("/api/positions/summary")
async def get_positions_summary():
    """Get portfolio summary."""
    pos_manager = get_pos_manager()
    summary = pos_manager.get_portfolio_summary()
    return summary

@router.post("/api/positions/{position_id}/sell")
async def sell_position(position_id: int, body: SellConfirmRequest):
    """Close (or partially reduce) a position.

    若 ``body.sell_action`` 是减仓动作（REDUCE_*），按对应比例部分
    减仓（持仓保持 holding，仅减少份额/成本）；否则按清仓处理。
    """
    pos_manager = get_pos_manager()
    ratio = parse_reduce_ratio(body.sell_action)
    if ratio is not None:
        # 取 etf_code 供减仓执行层标记对应卖出信号
        row = pos_manager.db.conn.execute(
            "SELECT etf_code FROM positions WHERE id=?", (position_id,)
        ).fetchone()
        etf_code = row["etf_code"] if row else None
        rt = get_data_provider().get_realtime_quote(etf_code) if etf_code else None
        current_price = rt["price"] if rt else None
        result = pos_manager.reduce_position(
            position_id, body.sell_price, ratio, body.sell_strategy,
            current_price=current_price, etf_code=etf_code,
            sell_action=body.sell_action,
        )
        if not result:
            raise HTTPException(404, "Position not found or nothing to reduce")
        return {"message": "减仓成功", "position": result, "action": body.sell_action}

    result = pos_manager.close_position(position_id, body.sell_price, body.sell_strategy)
    if not result:
        raise HTTPException(404, "Position not found")
    return {"message": "卖出成功", "position": result}


# ============ Strategy Parameters ============

@router.get("/api/strategy/params")
async def get_params():
    """Get all strategy parameters grouped by group."""
    db = get_db()
    params = db.get_strategy_params()
    grouped = {}
    for p in params:
        group = p["param_group"]
        if group not in grouped:
            grouped[group] = []
        grouped[group].append(p)
    return {"data": grouped}

@router.put("/api/strategy/params")
async def update_param(body: ParamUpdateRequest):
    """Update a strategy parameter."""
    db = get_db()
    db.set_param(body.key, body.value, body.group, body.description)
    return {"message": "参数已更新", "key": body.key, "value": body.value}

@router.post("/api/strategy/preset")
async def apply_preset(body: PresetApplyRequest):
    """Apply a preset template (conservative/standard/aggressive)."""
    db = get_db()
    presets = {
        "conservative": {
            "weight_trend": "0.30", "weight_momentum": "0.10", "weight_volume": "0.10",
            "weight_volatility": "0.20", "weight_technical": "0.30",
        },
        "standard": {
            "weight_trend": "0.25", "weight_momentum": "0.20", "weight_volume": "0.15",
            "weight_volatility": "0.10", "weight_technical": "0.30",
        },
        "aggressive": {
            "weight_trend": "0.30", "weight_momentum": "0.30", "weight_volume": "0.10",
            "weight_volatility": "0.05", "weight_technical": "0.25",
        },
    }
    preset = presets.get(body.preset)
    if not preset:
        raise HTTPException(400, f"Unknown preset: {body.preset}")
    for key, value in preset.items():
        db.set_param(key, value, "factor", f"预设模板{body.preset}")
    return {"message": f"已应用{body.preset}预设模板", "params": preset}

@router.post("/api/strategy/reset")
async def reset_params():
    """Reset all parameters to defaults."""
    db = get_db()
    # Clear and re-init
    db.conn.execute("DELETE FROM strategy_params")
    db.init_default_params()
    return {"message": "参数已重置为默认值"}


# ============ Performance ============

@router.get("/api/performance")
async def get_performance():
    """Get performance statistics."""
    db = get_db()
    stats = db.get_performance_stats()
    closed = db.get_closed_positions()

    # Calculate monthly stats
    monthly: dict[str, dict] = {}
    for t in closed:
        month = (t.get("sell_date") or "")[:7]  # YYYY-MM
        if not month:
            continue
        if month not in monthly:
            monthly[month] = {"month": month, "trades": 0, "wins": 0, "pnl": 0.0}
        monthly[month]["trades"] += 1
        if (t.get("sell_pnl_amount") or 0) > 0:
            monthly[month]["wins"] += 1
        monthly[month]["pnl"] += t.get("sell_pnl_amount", 0)

    monthly_list = sorted(monthly.values(), key=lambda x: x["month"], reverse=True)
    for m in monthly_list:
        m["win_rate"] = round(m["wins"] / m["trades"] * 100, 1) if m["trades"] else 0
        m["pnl"] = round(m["pnl"], 2)

    # Sell strategy distribution
    strategy_dist: dict[str, dict] = {}
    for t in closed:
        s = t.get("sell_strategy") or "手动"
        if s not in strategy_dist:
            strategy_dist[s] = {"strategy": s, "count": 0, "total_pnl": 0.0}
        strategy_dist[s]["count"] += 1
        strategy_dist[s]["total_pnl"] += t.get("sell_pnl_amount", 0)

    for s in strategy_dist.values():
        s["total_pnl"] = round(s["total_pnl"], 2)
        s["avg_pnl"] = round(s["total_pnl"] / s["count"], 2) if s["count"] else 0

    # 待买入池历史记录（卖出扫描标记为「已卖出」的项）
    pool_sold = db.get_pending_pool("sold")

    return {
        "stats": stats,
        "monthly": monthly_list,
        "strategy_distribution": list(strategy_dist.values()),
        "trades": closed,
        "pool_history": pool_sold,
    }


# ============ Realtime ============

@router.get("/api/realtime")
async def get_realtime_quotes(codes: Optional[str] = Query(None)):
    """Get real-time quotes for all or specific ETFs."""
    mock = get_data_provider()
    if codes:
        code_list = codes.split(",")
        quotes = [mock.get_realtime_quote(c) for c in code_list if mock.get_realtime_quote(c)]
    else:
        quotes = mock.get_all_realtime_quotes()
    return {"data": quotes, "total": len(quotes)}

@router.post("/api/realtime/tick")
async def tick_realtime():
    """Refresh realtime quotes from data source (rate-limited to min 60s interval)."""
    provider = get_data_provider()
    success = provider.update_realtime()
    if success:
        return {"message": "行情已更新", "timestamp": now_cst().strftime("%H:%M:%S")}
    else:
        # Throttled — return cached data timestamp
        last = getattr(provider, '_last_realtime_update', 0)
        last_str = datetime.fromtimestamp(last).strftime("%H:%M:%S") if last else "N/A"
        return {
            "message": "行情刷新被限流（最小间隔60秒）",
            "last_update": last_str,
            "timestamp": now_cst().strftime("%H:%M:%S"),
        }


# ============ Realtime Scanner Daemon ============

@router.get("/api/scanner/status")
async def get_scanner_status():
    """Get realtime scanner daemon status (running, scan count, last scan)."""
    return get_scanner().get_status()


@router.get("/api/universe")
async def get_scan_universe():
    """Return the current scan universe (whitelist small pool) and K-line cache stats.

    Observability for the real-data performance optimization: shows how many ETFs
    the scanner actually screens versus the full market, and how many K-lines are
    served from the persistent on-disk cache (avoiding network re-fetch).
    """
    screening = get_screening()
    provider = get_data_provider()
    universe = screening.get_scan_universe()
    use_whitelist = settings.DATA_SOURCE == "akshare" and settings.USE_WHITELIST_POOL

    payload = {
        "data_source": settings.DATA_SOURCE,
        "use_whitelist": use_whitelist,
        "whitelist_size": len(settings.ETF_WHITELIST),
        "universe_size": len(universe),
        "universe": [
            {"code": e.code, "name": e.name, "status": e.status} for e in universe
        ],
    }
    if hasattr(provider, "get_health_status"):
        health = provider.get_health_status()
        payload["kline_persistent_cached"] = health.get("cache", {}).get(
            "kline_persistent_cached", 0
        )
    else:
        payload["kline_persistent_cached"] = 0
    # Indicator cache stats (P2: collapses per-round N+1 recompute)
    payload["indicator_cache"] = get_indicator_cache().stats()
    return payload


@router.post("/api/scanner/start")
async def start_scanner():
    """Start the realtime scanner daemon manually."""
    get_scanner().start()
    return {"message": "实时扫描守护进程已启动", **get_scanner().get_status()}


@router.post("/api/scanner/stop")
async def stop_scanner():
    """Stop the realtime scanner daemon manually."""
    get_scanner().stop()
    return {"message": "实时扫描守护进程已停止", **get_scanner().get_status()}


@router.post("/api/scanner/force-scan")
async def force_scan():
    """Force one scan immediately (works even outside trading hours). Useful for debug / manual trigger."""
    scanner = get_scanner()
    await scanner._do_scan()
    return scanner.last_scan or {"message": "no scan result"}


@router.get("/api/scanner/stream")
async def scanner_stream():
    """Server-Sent Events stream of realtime scan results (push on every scan).

    使用 SSE 而非 WebSocket，避免依赖 websockets/wsproto 传输库；浏览器侧
    用 EventSource 即可消费，满足 PRD 的「实时推送」需求。
    """
    scanner = get_scanner()
    queue = scanner.subscribe()

    async def event_gen():
        # 连接即推送最近一次快照
        if scanner.last_scan:
            yield f"data: {json.dumps(scanner.last_scan, ensure_ascii=False)}\n\n"
        try:
            while True:
                payload = await queue.get()
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            scanner.unsubscribe(queue)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ============ 交易看板 (Market Indices) ============

@router.get("/api/indices")
async def get_indices():
    """Get real-time quotes for major A-share indices + Hang Seng + market breadth.

    交易看板核心接口：覆盖 上证指数 / 深证成指 / 创业板指 / 科创50 /
    沪深300 / 上证50 / 北证50 / 恒生指数（港股），并附带涨跌家数（市场宽度）。
    真实数据优先（akshare 可联网时），离线/本地开发自动降级为 mock 生成器。
    """
    provider = get_index_provider()
    return provider.get_index_quotes()


@router.get("/api/indices/{code}/klines")
async def get_index_klines(code: str, days: int = Query(60, ge=5, le=250)):
    """Get daily K-line history for a single index (for the board's chart)."""
    provider = get_index_provider()
    return provider.get_index_klines(code, days)


# ============ Data Source Health ============

@router.get("/api/health/data-source")
async def get_data_source_health():
    """Get health status of data sources, rate limiters, and circuit breakers."""
    provider = get_data_provider()
    if hasattr(provider, 'get_health_status'):
        health = provider.get_health_status()
    else:
        health = {"data_source": settings.DATA_SOURCE, "message": "Mock provider — no rate limits"}
    # Indicator cache stats (P2: collapses per-round N+1 recompute)
    health["indicator_cache"] = get_indicator_cache().stats()
    return health

@router.post("/api/health/circuit-breaker/reset")
async def reset_circuit_breakers():
    """Manually reset all circuit breakers to CLOSED state."""
    from src.infrastructure.rate_limiter import ALL_BREAKERS
    for breaker in ALL_BREAKERS:
        breaker.reset()
    return {"message": "All circuit breakers reset to CLOSED", "breakers": [b.name for b in ALL_BREAKERS]}
