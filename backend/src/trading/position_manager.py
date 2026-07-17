"""Position manager: tracks holdings, updates PnL, detects trend stocks."""

from datetime import datetime, timedelta
from typing import Optional
import numpy as np

from src.domain.entities import Position
from src.domain.enums import PositionStatus
from src.infrastructure.data_provider_factory import get_data_provider
from src.infrastructure.indicator_cache import (
    is_trend_stock_cached,
    DEFAULT_INDICATOR_DAYS,
)
from src.infrastructure.timeutil import now_cst
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

    def get_available_capital(self) -> float:
        """可用资金 = 总资金 - 当前持仓已投入成本。"""
        positions = self.db.get_holding_positions()
        invested = sum(float(p["buy_amount"]) for p in positions)
        return round(settings.TOTAL_CAPITAL - invested, 2)

    def suggested_buy_amount(self) -> float:
        """建议买入金额：受单只上限与总仓位上限双重约束，并扣除已持仓。

        计算：
          - 单只上限   = 总资金 × SINGLE_POSITION_LIMIT
          - 总仓位余量 = 总资金 × TOTAL_POSITION_LIMIT - 已投入
          - 可用资金   = 总资金 - 已投入
          suggested = max(0, min(单只上限, 总仓位余量, 可用资金))
        """
        avail = self.get_available_capital()
        single_cap = settings.TOTAL_CAPITAL * settings.SINGLE_POSITION_LIMIT
        invested = settings.TOTAL_CAPITAL - avail
        total_room = settings.TOTAL_CAPITAL * settings.TOTAL_POSITION_LIMIT - invested
        suggested = min(single_cap, total_room, avail)
        return round(max(suggested, 0.0), 2)

    def confirm_buy(self, signal_id: str, etf_code: str, etf_name: str,
                    buy_price: float, buy_amount: float,
                    buy_signal_id: Optional[str] = None) -> dict:
        """Confirm a buy signal and create a new position.

        Returns the created position dict.
        约束（修复 P1-1/P1-2）：
          - 买入金额须 > 0
          - 买入金额不得超过可用资金（已达总仓位上限则拒绝）
          - 同一 ETF 不可重复开仓（持仓中已存在则拒绝）
          - 写入信号状态/建仓/更新盈亏 在一个事务内完成，失败回滚
        """
        if buy_amount <= 0:
            raise ValueError("买入金额必须大于 0")
        avail = self.get_available_capital()
        invested = settings.TOTAL_CAPITAL - avail
        total_room = settings.TOTAL_CAPITAL * settings.TOTAL_POSITION_LIMIT - invested
        # 同时受「可用资金」与「总仓位上限余量」约束，取两者较小值
        max_allowed = min(avail, total_room)
        if buy_amount > max_allowed + 1e-6:
            raise ValueError(
                f"买入金额 {buy_amount:.2f} 超出可用资金 {avail:.2f}（已触达总仓位上限 {settings.TOTAL_POSITION_LIMIT*100:.0f}%）"
            )
        if self.db.has_open_position(etf_code):
            raise ValueError(f"{etf_code} 已在持仓中，不能重复开仓")

        buy_date = now_cst().strftime("%Y-%m-%d")
        buy_shares = buy_amount / buy_price if buy_price > 0 else 0

        # Check if ETF is already a trend stock (cached indicators)
        is_trend = is_trend_stock_cached(self.mock, etf_code, DEFAULT_INDICATOR_DAYS)

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

        # 事务：信号状态 + 建仓 + 盈亏初始化 一体提交，任一失败回滚
        try:
            self.db.conn.execute("BEGIN")
            pos_id = self.db.save_position(pos_data, commit=False)
            self.db.update_signal_status(signal_id, "confirmed", commit=False)
            self.db.update_position_pnl(
                pos_id, buy_price, buy_amount, 0, 0, 0, is_trend, commit=False
            )
            self.db.conn.commit()
        except Exception:
            self.db.conn.rollback()
            raise

        pos_data["id"] = pos_id
        return pos_data

    def update_all_positions(self) -> list[dict]:
        """Update PnL for all holding positions. Returns updated positions."""
        positions = self.db.get_holding_positions()
        today = now_cst().date()

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

            # Calculate hold days (date arithmetic — both sides naive date)
            buy_date = datetime.strptime(pos["buy_date"], "%Y-%m-%d").date()
            hold_days = (today - buy_date).days

            # Re-check trend stock status (cached indicators)
            is_trend = is_trend_stock_cached(self.mock, etf_code, DEFAULT_INDICATOR_DAYS)

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
        """Close a position at the given sell price (transactional)."""
        sell_date = datetime.now().strftime("%Y-%m-%d")
        try:
            self.db.conn.execute("BEGIN")
            result = self.db.close_position(
                pos_id, sell_price, sell_date, sell_strategy, commit=False
            )
            self.db.conn.commit()
        except Exception:
            self.db.conn.rollback()
            raise
        return result

    def reduce_position(self, pos_id: int, sell_price: float, ratio: float,
                        sell_strategy: str, current_price: Optional[float] = None,
                        etf_code: Optional[str] = None,
                        sell_action: Optional[str] = None) -> dict:
        """按 ``ratio`` 部分减仓（REDUCE_* 动作落地）。

        与 ``close_position`` 不同：持仓保持 ``holding``，仅按占比减少
        份额/成本并结算已实现盈亏；同时把对应的待处理卖出信号
        标记为 executed，避免它继续挂在待处理列表里。
        """
        sell_date = now_cst().strftime("%Y-%m-%d")
        # 取 etf_code 用于标记信号（若未传则从库里查）
        if etf_code is None:
            row = self.db.conn.execute(
                "SELECT etf_code FROM positions WHERE id=?", (pos_id,)
            ).fetchone()
            etf_code = row["etf_code"] if row else None
        try:
            self.db.conn.execute("BEGIN")
            result = self.db.partial_sell_position(
                pos_id, sell_price, ratio, sell_date, sell_strategy,
                current_price=current_price, commit=False
            )
            if result and etf_code:
                # 按减仓动作(sell_action)匹配待处理信号并标记 executed，
                # 与 UI 契约(英文动作)和卖出引擎落库(英文动作)对齐；
                # sell_strategy 为兼容旧调用兜底。
                self.db.mark_sell_signal_executed(
                    etf_code, sell_action or sell_strategy,
                    result.get("realized_pnl_amount", 0),
                    result.get("realized_pnl_pct", 0),
                    commit=False
                )
            self.db.conn.commit()
        except Exception:
            self.db.conn.rollback()
            raise
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
