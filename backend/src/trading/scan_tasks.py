"""Shared scan tasks reused by manual REST endpoints and the realtime daemon.

Extracting this logic keeps the daemon and the API endpoints perfectly aligned
so auto-scanning produces exactly the same signals a manual scan would.
"""

from datetime import datetime

from config import settings
from src.trading.buy_signal import BuySignalEngine
from src.trading.position_manager import PositionManager
from src.screening.screening_engine import ScreeningEngine


def _buy_signal_to_dict(signal) -> dict:
    """Convert a BuySignal domain object into the DB/payload dict."""
    return {
        "signal_id": signal.signal_id,
        "signal_type": "buy",
        "etf_code": signal.etf_code,
        "etf_name": signal.etf_name,
        "trigger_time": signal.trigger_time,
        "trigger_details": signal.trigger_details,
        "price": signal.price,
        "change_pct": signal.change_pct,
        "suggested_amount": signal.suggested_amount,
        "factor_summary": signal.factor_summary,
        "status": "pending",
    }


def run_buy_scan(screening: ScreeningEngine, buy_engine: BuySignalEngine,
                 pos_manager: PositionManager, db) -> dict:
    """Run buy-signal scan over today's recommended ETFs. Returns summary dict."""
    is_empty, reason = screening.check_market_empty_signal()
    if is_empty:
        return {"message": "市场空仓信号", "reason": reason,
                "scanned": 0, "triggered": 0, "signals": []}

    recommendations = screening.get_today_recommendations()
    if not recommendations:
        return {"message": "今日无推荐ETF", "scanned": 0, "triggered": 0, "signals": []}

    candidate_codes = [r.etf_code for r in recommendations]

    # Cooldown filter
    sold_dates = pos_manager.get_recently_sold_codes()
    active_codes = [c for c in candidate_codes if not buy_engine.is_in_cooldown(c, sold_dates)]

    # Exclude already-held ETFs
    holdings = pos_manager.update_all_positions()
    held_codes = {p["etf_code"] for p in holdings}
    scan_codes = [c for c in active_codes if c not in held_codes]

    # Factor map for enrichment
    factor_map = {
        r.etf_code: {"score": r.layer2_score, "rank": r.layer2_rank, "theme": r.layer3_theme}
        for r in recommendations
    }

    signals = buy_engine.scan_candidates(scan_codes, factor_map)

    saved = []
    for signal in signals:
        signal_dict = _buy_signal_to_dict(signal)
        sig_id = db.save_signal(signal_dict)
        saved.append({**signal_dict, "signal_id": sig_id})

    return {"scanned": len(scan_codes), "triggered": len(saved), "signals": saved}


def run_sell_scan(pos_manager: PositionManager) -> dict:
    """Scan all holding positions for sell signals. Returns summary dict."""
    positions = pos_manager.db.get_holding_positions()
    sell_signals = pos_manager.check_holdings_for_sell()
    return {"scanned": len(positions), "triggered": len(sell_signals), "signals": sell_signals}
