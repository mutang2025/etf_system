"""Position manager: tracks holdings, updates PnL, detects trend stocks."""

from datetime import datetime, timedelta
from typing import Optional
import numpy as np

from src.domain.entities import Position
from src.domain.enums import PositionStatus
from src.indicators.technical import IndicatorCalculator, is_trend_stock
from src.infrastructure.data_provider_factory import get_data_provider
from src.infrastructure.database_repo import DatabaseRepository
from src.trading.sell_strategies import SellStrategyEngine
from config import settings


class PositionManager:
    """Manages ETF positions lifecycle from buy confirmation to sell."""

    def __init__(self, db: DatabaseRepository, data_provider=None):
        self.db = db
        self.mock = data_provider or get_data_provider()
        # 单例卖出引擎：日内峰值/未创新高计数器跨扫描调用累积，
        # 否则每次调用重建实例会让冲高回落(P70)与强制减仓(P65)永远不触发。
        self.sell_engine = SellStrategyEngine(self.mock)

    def confirm_buy(self, signal_id: str, etf_code: str, etf_name: str,
                    buy_price: float, buy_amount: float,
                    buy_signal_id: Optional[str] = None) -> dict:
        """Confirm a buy signal and create a new position.

        Returns the created position dict.
        """
        buy_date = datetime.now().strftime("%Y-%m-%d")
        buy_shares = buy_amount / buy_price if buy_price > 0 else 0

        # Check if ETF is already a trend stock
        klines = self.mock.get_klines(etf_code, 120)
        is_trend = False
        if klines and len(klines) >= 21:
            import pandas as pd
            df = pd.DataFrame([
                {"close": k.close, "open": k.open, "high": k.high, "low": k.low}
                for k in klines
            ])
            is_trend = is_trend_stock(df["close"], df["open"])

        pos_data = {
            "etf_code": etf_code,
            "etf_name": etf_name,
            "buy_signal_id": buy_signal_id or signal_id,
            "buy_date": buy_date,
            "buy_price": buy_price,
            "buy_amount": buy_amount,
            "buy_shares": round(buy_shares, 2),
            "current_price": buy_price,
            "current_value": buy_amount,
            "is_trend_stock": is_trend,
        }
        pos_id = self.db.save_position(pos_data)

        # Update signal status
        self.db.update_signal_status(signal_id, "confirmed")

        # Update PnL
        self.db.update_position_pnl(
            pos_id, buy_price, buy_amount, 0, 0, 0, is_trend
        )

        pos_data["id"] = pos_id
        return pos_data

    def update_all_positions(self) -> list[dict]:
        """Update PnL for all holding positions. Returns updated positions."""
        positions = self.db.get_holding_positions()
        today = datetime.now()

        for pos in positions:
            etf_code = pos["etf_code"]
            rt = self.mock.get_realtime_quote(etf_code)

            if not rt:
                continue

            current_price = rt["price"]
            buy_price = pos["buy_price"]
            buy_shares = pos["buy_shares"]
            current_value = current_price * buy_shares
            pnl_amount = (current_price - buy_price) * buy_shares
            pnl_pct = (current_price / buy_price - 1) * 100 if buy_price else 0

            # Calculate hold days
            buy_date = datetime.strptime(pos["buy_date"], "%Y-%m-%d")
            hold_days = (today - buy_date).days

            # Re-check trend stock status
            klines = self.mock.get_klines(etf_code, 120)
            is_trend = False
            if klines and len(klines) >= 21:
                import pandas as pd
                df = pd.DataFrame([
                    {"close": k.close, "open": k.open, "high": k.high, "low": k.low}
                    for k in klines
                ])
                is_trend = is_trend_stock(df["close"], df["open"])

            self.db.update_position_pnl(
                pos["id"], current_price, current_value,
                round(pnl_amount, 2), round(pnl_pct, 2),
                hold_days, is_trend
            )

            # Update in-memory
            pos["current_price"] = current_price
            pos["current_value"] = round(current_value, 2)
            pos["pnl_amount"] = round(pnl_amount, 2)
            pos["pnl_pct"] = round(pnl_pct, 2)
            pos["hold_days"] = hold_days
            pos["is_trend_stock"] = is_trend

        return positions

    def close_position(self, pos_id: int, sell_price: float,
                       sell_strategy: str = "manual") -> dict:
        """Close a position at the given sell price."""
        sell_date = datetime.now().strftime("%Y-%m-%d")
        result = self.db.close_position(pos_id, sell_price, sell_date, sell_strategy)
        return result

    def get_portfolio_summary(self) -> dict:
        """Get portfolio overview: total value, total PnL, position count."""
        positions = self.update_all_positions()
        total_value = sum(p["current_value"] for p in positions)
        total_pnl = sum(p["pnl_amount"] for p in positions)
        total_cost = sum(p["buy_amount"] for p in positions)
        total_pnl_pct = (total_value / total_cost - 1) * 100 if total_cost > 0 else 0

        return {
            "total_positions": len(positions),
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "total_capital": settings.TOTAL_CAPITAL,
            "available_capital": round(settings.TOTAL_CAPITAL - total_cost, 2),
            "position_ratio": round(total_cost / settings.TOTAL_CAPITAL * 100, 1) if settings.TOTAL_CAPITAL > 0 else 0,
            "trend_stocks": sum(1 for p in positions if p["is_trend_stock"]),
            "positions": positions,
        }

    def check_holdings_for_sell(self) -> list[dict]:
        """Check all holding positions against sell strategies.

        Returns list of sell signal dicts. 同一持仓+同一策略的待处理信号会去重，
        避免守护进程每轮扫描重复落库。
        """
        positions = self.update_all_positions()
        if not positions:
            return []

        # 组合层面未实现盈亏，用于紧急熔断（PRD 要求整体组合浮亏 > 5%）
        total_cost = sum(p["buy_amount"] for p in positions) or 0
        total_value = sum(p["current_value"] for p in positions)
        portfolio_pnl_pct = (total_value / total_cost - 1) * 100 if total_cost > 0 else 0

        sell_signals = []
        for pos in positions:
            signal = self.sell_engine.check_all_strategies(pos, portfolio_pnl_pct=portfolio_pnl_pct)
            if signal:
                # 去重：该持仓该策略今日已有待处理信号则跳过
                if self.db.has_pending_sell_signal(pos["etf_code"], signal.strategy_type):
                    continue
                # Save signal to DB
                signal_dict = {
                    "signal_id": signal.signal_id,
                    "signal_type": "sell",
                    "etf_code": signal.etf_code,
                    "etf_name": signal.etf_name,
                    "trigger_time": signal.trigger_time,
                    "price": signal.price,
                    "sell_strategy": signal.strategy_type,
                    "sell_priority": signal.priority,
                    "sell_action": signal.action,
                    "pnl_amount": signal.pnl_amount,
                    "pnl_pct": signal.pnl_pct,
                    "status": "pending",
                }
                signal_id = self.db.save_signal(signal_dict)
                sell_signals.append({
                    **signal_dict,
                    "signal_id": signal_id,
                    "buy_price": signal.buy_price,
                    "hold_days": signal.hold_days,
                    "position_id": pos["id"],
                })

        return sell_signals

    def get_recently_sold_codes(self) -> dict:
        """Get dict of recently sold ETF codes with sell dates (for cooldown check)."""
        closed = self.db.get_closed_positions()
        result = {}
        for pos in closed:
            if pos.get("sell_date"):
                result[pos["etf_code"]] = pos["sell_date"]
        return result
