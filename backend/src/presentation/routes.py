"""REST API routes for the ETF trading system."""

import asyncio
import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from src.infrastructure.database_repo import DatabaseRepository
from src.infrastructure.data_provider_factory import get_data_provider
from src.screening.screening_engine import ScreeningEngine
from src.trading.buy_signal import BuySignalEngine
from src.trading.position_manager import PositionManager
from src.trading.scan_tasks import run_buy_scan, run_sell_scan
from src.realtime_scanner import get_scanner
from config import settings

router = APIRouter()

# Initialize services lazily
_db: Optional[DatabaseRepository] = None
_screening: Optional[ScreeningEngine] = None
_buy_engine: Optional[BuySignalEngine] = None
_pos_manager: Optional[PositionManager] = None


def get_db() -> DatabaseRepository:
    global _db
    if _db is None:
        _db = DatabaseRepository()
        _db.init_default_params()
    return _db


def get_screening() -> ScreeningEngine:
    global _screening
    if _screening is None:
        _screening = ScreeningEngine()
    return _screening


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

class BuyConfirmRequest(BaseModel):
    etf_code: str
    etf_name: str
    buy_price: float
    buy_amount: float

class SellConfirmRequest(BaseModel):
    position_id: int
    sell_price: float
    sell_strategy: str = "manual"

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
    today = datetime.now().strftime("%Y-%m-%d")
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
            "is_trading_day": datetime.now().weekday() < 5,
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
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """Get ETF pool with filters."""
    db = get_db()
    etfs = db.get_etf_pool(status=status, etf_type=etf_type)
    total = len(etfs)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "data": etfs[start:end],
    }

@router.get("/api/etf-pool/{code}")
async def get_etf_detail(code: str):
    """Get single ETF detail with K-line data."""
    db = get_db()
    mock = get_data_provider()
    etf = db.get_etf(code)
    if not etf:
        raise HTTPException(404, "ETF not found")
    # Try DB first, fallback to provider (K-lines not synced for all ETFs with AKShare)
    klines = db.get_klines_from_db(code, 30)
    if not klines:
        # Fetch from provider on demand
        provider_klines = mock.get_klines(code, 30)
        klines = [{"etf_code": k.etf_code, "trade_date": k.trade_date,
                   "open": k.open, "high": k.high, "low": k.low,
                   "close": k.close, "volume": k.volume, "amount": k.amount}
                  for k in provider_klines]
    rt = mock.get_realtime_quote(code)
    return {"etf": etf, "klines": klines[-30:], "realtime": rt}

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

    # Save results to DB
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

    summary = screening.get_screening_summary(results)

    # 手动重跑选股后使当日推荐缓存失效，下一轮买入扫描将取到最新结果
    screening.invalidate_cache()

    # If empty signal, save it
    if is_empty:
        db.save_signal({
            "signal_type": "empty",
            "trigger_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "pending",
        })

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
    }

@router.get("/api/screening/results")
async def get_screening_results(select_date: Optional[str] = None):
    """Get screening results for a date (default: today)."""
    db = get_db()
    date = select_date or datetime.now().strftime("%Y-%m-%d")
    results = db.get_selection_results(date)
    return {"select_date": date, "data": results}


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

    # Update signal status
    db.update_signal_status(signal_id, "confirmed")

    # Create position
    position = pos_manager.confirm_buy(
        signal_id=signal_id,
        etf_code=body.etf_code,
        etf_name=body.etf_name,
        buy_price=body.buy_price,
        buy_amount=body.buy_amount,
    )
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
    """Close a position."""
    pos_manager = get_pos_manager()
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

    return {
        "stats": stats,
        "monthly": monthly_list,
        "strategy_distribution": list(strategy_dist.values()),
        "trades": closed,
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
        return {"message": "行情已更新", "timestamp": datetime.now().strftime("%H:%M:%S")}
    else:
        # Throttled — return cached data timestamp
        last = getattr(provider, '_last_realtime_update', 0)
        last_str = datetime.fromtimestamp(last).strftime("%H:%M:%S") if last else "N/A"
        return {
            "message": "行情刷新被限流（最小间隔60秒）",
            "last_update": last_str,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
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


# ============ Data Source Health ============

@router.get("/api/health/data-source")
async def get_data_source_health():
    """Get health status of data sources, rate limiters, and circuit breakers."""
    provider = get_data_provider()
    if hasattr(provider, 'get_health_status'):
        return provider.get_health_status()
    return {"data_source": settings.DATA_SOURCE, "message": "Mock provider — no rate limits"}

@router.post("/api/health/circuit-breaker/reset")
async def reset_circuit_breakers():
    """Manually reset all circuit breakers to CLOSED state."""
    from src.infrastructure.rate_limiter import ALL_BREAKERS
    for breaker in ALL_BREAKERS:
        breaker.reset()
    return {"message": "All circuit breakers reset to CLOSED", "breakers": [b.name for b in ALL_BREAKERS]}
