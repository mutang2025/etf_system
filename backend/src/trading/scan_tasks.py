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
from src.domain.enums import parse_reduce_ratio

import time

# --------------------------------------------------------------------------
# 自动交易：信号触发即自动成交（默认关闭，由 AUTO_EXECUTE_BUY/SELL 控制）
# --------------------------------------------------------------------------

# 同一持仓同一卖出策略的自动执行冷却：守护进程每 SCAN_INTERVAL_SECONDS(默认10s)
# 一轮扫描，若对「强制减仓」等可重复触发的减仓策略不设冷却，会反复减仓直至清仓。
_AUTO_SELL_GUARD: dict = {}


def _auto_sell_allowed(key: tuple) -> bool:
    """冷却期内返回 False，避免同一持仓同一策略被守护进程循环重复卖出。"""
    last = _AUTO_SELL_GUARD.get(key)
    if last is None:
        return True
    return (time.monotonic() - last) >= settings.AUTO_SELL_COOLDOWN_SECONDS


def _record_auto_sell(key: tuple) -> None:
    _AUTO_SELL_GUARD[key] = time.monotonic()


def auto_confirm_buy(pos_manager: PositionManager, db, signal, sig_id: str) -> bool:
    """若启用自动买入，直接确认建仓。复用 confirm_buy 内部的资金上限 / 重复开仓校验；
    校验失败（资金不足、已持仓等）时返回 False，信号保留为 pending 供手动处理。
    """
    if not settings.AUTO_EXECUTE_BUY:
        return False
    try:
        pos_manager.confirm_buy(
            signal_id=sig_id, etf_code=signal.etf_code, etf_name=signal.etf_name,
            buy_price=signal.price, buy_amount=signal.suggested_amount,
            buy_signal_id=sig_id,
        )
        db.remove_from_pool(signal.etf_code)
        return True
    except ValueError:
        return False


def auto_execute_sell(pos_manager: PositionManager, sig: dict) -> bool:
    """若启用自动卖出，按信号动作执行清仓 / 减仓，并标记对应卖出信号为 executed。"""
    if not settings.AUTO_EXECUTE_SELL:
        return False
    key = (sig["etf_code"], sig.get("sell_strategy"))
    if not _auto_sell_allowed(key):
        return False
    pos_id = sig.get("position_id")
    action = sig.get("sell_action")
    price = sig.get("price")
    ratio = parse_reduce_ratio(action)
    try:
        if ratio is not None:
            # 减仓动作：部分卖出，持仓保持 holding（reduce_position 内部已标记信号）
            result = pos_manager.reduce_position(
                pos_id, price, ratio,
                sell_strategy=sig.get("sell_strategy") or "auto",
                etf_code=sig["etf_code"], sell_action=action,
            )
        else:
            # 清仓 / 止损：整仓平仓（close 不会标记信号，需手动标记）
            result = pos_manager.close_position(
                pos_id, price, sell_strategy=sig.get("sell_strategy") or "auto",
            )
            if result:
                pos_manager.db.mark_sell_signal_executed(
                    sig["etf_code"], action,
                    result.get("sell_pnl_amount", 0),
                    result.get("sell_pnl_pct", 0),
                )
        if not result:
            return False
        _record_auto_sell(key)
        return True
    except Exception:
        return False


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
    auto_buy_executed = []
    for signal in signals:
        signal_dict = _buy_signal_to_dict(signal)
        sig_id = db.save_signal(signal_dict)
        full = {**signal_dict, "signal_id": sig_id}
        saved.append(full)

        # 自动纳入待买入池：记录入池点位 = 信号触发时现价
        rt = buy_engine.mock.get_realtime_quote(signal.etf_code)
        entry_price = rt["price"] if rt else signal.price
        db.add_to_pool(
            signal.etf_code, signal.etf_name, entry_price,
            now_cst().strftime("%Y-%m-%d %H:%M:%S"),
        )

        # 自动买入：信号触发即确认建仓（受 confirm_buy 资金/重复校验保护）
        if auto_confirm_buy(pos_manager, db, signal, sig_id):
            full["status"] = "confirmed"
            auto_buy_executed.append(signal.etf_code)

    return {
        "scanned": len(scan_codes),
        "triggered": len(saved),
        "signals": saved,
        "auto_buy_executed": auto_buy_executed,
    }


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

    # 自动卖出：持仓卖出信号触发即执行（受 AUTO_EXECUTE_SELL 控制 + 同策略冷却守卫）
    auto_sell_executed = []
    for sig in sell_signals:
        if auto_execute_sell(pos_manager, sig):
            sig["status"] = "executed"
            auto_sell_executed.append(sig["signal_id"])

    return {
        "scanned": len(positions),
        "triggered": len(sell_signals),
        "signals": sell_signals,
        "pool_sold": pool_sold,
        "auto_sell_executed": auto_sell_executed,
    }
