"""Shared scan tasks reused by manual REST endpoints and the realtime daemon.

Extracting this logic keeps the daemon and the API endpoints perfectly aligned
so auto-scanning produces exactly the same signals a manual scan would.
"""

from datetime import datetime

from config import settings
from src.infrastructure.timeutil import now_cst
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

    # 买入扫描宇宙 = 通过 layer4 风险过滤的全部 ETF（约 8–10 只），
    # 而非仅 top-N 最终推荐，避免错过"过审但未进前 N"的买点。
    layer4 = screening.get_today_layer4_passed()
    if not layer4:
        return {"message": "今日无通过层4筛选的ETF", "scanned": 0, "triggered": 0, "signals": []}

    # Final top-N picks kept only as a priority hint, NOT as the scan universe.
    final_codes = {r.etf_code for r in screening.get_today_recommendations()}

    candidate_codes = [r.etf_code for r in layer4]

    # Cooldown filter
    sold_dates = pos_manager.get_recently_sold_codes()
    active_codes = [c for c in candidate_codes if not buy_engine.is_in_cooldown(c, sold_dates)]

    # Exclude already-held ETFs
    holdings = pos_manager.update_all_positions()
    held_codes = {p["etf_code"] for p in holdings}
    scan_codes = [c for c in active_codes if c not in held_codes]

    # Factor map for enrichment (covers all scanned codes; marks top picks)
    factor_map = {
        r.etf_code: {
            "score": r.layer2_score, "rank": r.layer2_rank,
            "theme": r.layer3_theme, "is_top_pick": r.final_recommended,
        }
        for r in layer4
    }

    # 可用资金（受总仓位上限约束的建议金额需要）
    available = pos_manager.get_available_capital()

    signals = buy_engine.scan_candidates(scan_codes, factor_map, available)

    saved = []
    for signal in signals:
        signal_dict = _buy_signal_to_dict(signal)
        sig_id = db.save_signal(signal_dict)
        saved.append({**signal_dict, "signal_id": sig_id})

        # 自动纳入待买入池：记录入池点位 = 信号触发时现价
        rt = buy_engine.mock.get_realtime_quote(signal.etf_code)
        entry_price = rt["price"] if rt else signal.price
        db.add_to_pool(
            signal.etf_code, signal.etf_name, entry_price,
            now_cst().strftime("%Y-%m-%d %H:%M:%S"),
        )

    return {"scanned": len(scan_codes), "triggered": len(saved), "signals": saved}


def run_sell_scan(pos_manager: PositionManager) -> dict:
    """Scan all holding positions AND the pending-buy pool for sell signals.

    Pool items are evaluated with the SAME sell-signal engine as holdings,
    using the recorded entry_price as cost basis. A triggered pool item is
    marked sold (records sell price, computes pnl_pct, status -> 'sold'),
    and stays in the list until manually removed. Sold pool items are no
    longer re-added by buy scans (blacklisted via the kept row).
    """
    positions = pos_manager.db.get_holding_positions()
    sell_signals = pos_manager.check_holdings_for_sell()

    # 待买入池也纳入卖出扫描：以入池点位为成本，跑同持仓卖出信号引擎
    pool_sold = []
    for item in pos_manager.db.get_pending_pool(status="watching"):
        rt = pos_manager.mock.get_realtime_quote(item["etf_code"])
        if not rt:
            continue
        pseudo = {
            "etf_code": item["etf_code"],
            "etf_name": item["etf_name"],
            "buy_price": item["entry_price"],
            "buy_shares": 0,
            "hold_days": 0,
            "is_trend_stock": False,
            "current_price": rt["price"],
        }
        sig = pos_manager.sell_engine.check_all_strategies(pseudo)
        if sig:
            sell_price = rt["price"]
            entry = item["entry_price"]
            pnl_pct = (sell_price / entry - 1) * 100 if entry else 0
            pos_manager.db.mark_pool_sold(
                item["etf_code"], sell_price,
                now_cst().strftime("%Y-%m-%d %H:%M:%S"), round(pnl_pct, 2),
            )
            pool_sold.append({
                "etf_code": item["etf_code"],
                "etf_name": item["etf_name"],
                "entry_price": entry,
                "sell_price": sell_price,
                "pnl_pct": round(pnl_pct, 2),
                "strategy_type": sig.strategy_type,
            })

    return {
        "scanned": len(positions),
        "triggered": len(sell_signals),
        "signals": sell_signals,
        "pool_sold": pool_sold,
    }
