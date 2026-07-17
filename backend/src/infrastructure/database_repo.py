"""SQLite database repository for persisting ETF system data."""

import json
import math
import sqlite3
from datetime import datetime
from typing import Optional
from config import settings
from src.domain.entities import ETF, DailyKline, Position
from src.infrastructure.data_provider_factory import get_data_provider
from src.infrastructure.timeutil import now_cst


class DatabaseRepository:
    """Repository for all database operations."""

    def __init__(self, conn: Optional[sqlite3.Connection] = None):
        self.conn = conn or get_connection()
        self.mock = get_data_provider()

    def sync_etf_pool(self) -> dict:
        """Sync ETF pool metadata from data provider to database. Returns sync stats.
        
        Note: K-line data is NOT synced here for all ETFs (too slow with real data sources).
        K-lines are fetched on demand by the screening engine and cached by the provider.
        """
        etfs = self.mock.get_etf_pool()
        today = now_cst().strftime("%Y-%m-%d")
        added = 0
        updated = 0

        for etf in etfs:
            existing = self.conn.execute(
                "SELECT code FROM etf_pool WHERE code = ?", (etf.code,)
            ).fetchone()

            if existing:
                self.conn.execute("""
                    UPDATE etf_pool SET name=?, exchange=?, etf_type=?, track_index=?,
                        theme=?, list_date=?, avg_amount_20d=?, total_market_cap=?,
                        status=?, data_status=?, synced_date=?, updated_at=datetime('now','localtime')
                    WHERE code=?
                """, (etf.name, etf.exchange, etf.etf_type, etf.track_index,
                      etf.theme, etf.list_date, etf.avg_amount_20d, etf.total_market_cap,
                      etf.status, etf.data_status, today, etf.code))
                updated += 1
            else:
                self.conn.execute("""
                    INSERT INTO etf_pool (code, name, exchange, etf_type, track_index,
                        theme, list_date, avg_amount_20d, total_market_cap,
                        status, data_status, synced_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (etf.code, etf.name, etf.exchange, etf.etf_type, etf.track_index,
                      etf.theme, etf.list_date, etf.avg_amount_20d, etf.total_market_cap,
                      etf.status, etf.data_status, today))
                added += 1

        # Sync HS300 index data (single API call, safe to sync)
        hs300_klines = self.mock.get_hs300_klines(120)
        for k in hs300_klines:
            self.conn.execute("""
                INSERT OR REPLACE INTO index_daily (index_code, trade_date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, ("000300.SH", k.trade_date, k.open, k.high, k.low, k.close, k.volume))

        # Log sync
        total = len(etfs)
        self.conn.execute("""
            INSERT INTO pool_sync_log (sync_date, added_count, removed_count, total_count, sync_status)
            VALUES (?, ?, 0, ?, 'success')
        """, (today, added, total))
        self.conn.commit()

        return {"added": added, "updated": updated, "total": total}

    def get_etf_pool(self, status: Optional[str] = None, etf_type: Optional[str] = None) -> list[dict]:
        """Get ETF pool from database with optional filters.

        Enriches each row with the live daily change % (change_pct) from the
        real-time quote cache (mock or akshare provider). Falls back to None
        when no quote is available (e.g. excluded/bond ETFs).
        """
        query = "SELECT * FROM etf_pool WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if etf_type:
            query += " AND etf_type = ?"
            params.append(etf_type)
        query += " ORDER BY avg_amount_20d DESC"
        rows = self.conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            rt = self.mock.get_realtime_quote(d["code"])
            d["change_pct"] = (
                round(float(rt["change_pct"]), 2)
                if rt and rt.get("change_pct") is not None
                else None
            )
            result.append(d)
        return result

    def get_etf(self, code: str) -> Optional[dict]:
        """Get a single ETF by code."""
        row = self.conn.execute("SELECT * FROM etf_pool WHERE code = ?", (code,)).fetchone()
        return dict(row) if row else None

    def update_etf_status(self, code: str, status: str) -> bool:
        """Update ETF status (e.g., add to blacklist)."""
        cursor = self.conn.execute(
            "UPDATE etf_pool SET status=?, updated_at=datetime('now','localtime') WHERE code=?",
            (status, code)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_klines_from_db(self, etf_code: str, days: int = 120) -> list[dict]:
        """Get K-line data from database."""
        rows = self.conn.execute("""
            SELECT * FROM daily_kline WHERE etf_code = ?
            ORDER BY trade_date DESC LIMIT ?
        """, (etf_code, days)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def save_selection_result(self, result: dict) -> None:
        """Save a screening result to database."""
        self.conn.execute("""
            INSERT OR REPLACE INTO selection_results
                (select_date, etf_code, etf_name, layer1_passed, layer2_score, layer2_rank,
                 layer2_factor_details, layer3_theme, layer3_theme_rank, layer3_passed,
                 layer4_death_cross, layer4_vol_price_div, layer4_adx_danger, layer4_bb_risk,
                 layer4_passed, final_recommended)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result["select_date"], result["etf_code"], result["etf_name"],
            int(result["layer1_passed"]), result["layer2_score"], result["layer2_rank"],
            json.dumps(result.get("factor_scores", []), ensure_ascii=False),
            result["layer3_theme"], result["layer3_theme_rank"], int(result["layer3_passed"]),
            int(result["layer4_death_cross"]), int(result["layer4_vol_price_div"]),
            int(result["layer4_adx_danger"]), int(result["layer4_bb_risk"]),
            int(result["layer4_passed"]), int(result["final_recommended"])
        ))
        self.conn.commit()

    def get_selection_results(self, select_date: str) -> list[dict]:
        """Get selection results for a date."""
        rows = self.conn.execute("""
            SELECT * FROM selection_results WHERE select_date = ?
            ORDER BY layer2_score DESC
        """, (select_date,)).fetchall()
        return [dict(r) for r in rows]

    def save_screening_run(self, select_date: str, funnel: dict) -> None:
        """Persist the full-pipeline funnel snapshot for a screening run."""
        self.conn.execute("""
            INSERT OR REPLACE INTO screening_runs
                (select_date, pool_total, layer1, layer2, layer3, layer4, final)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            select_date,
            int(funnel.get("pool_total", 0)),
            int(funnel.get("layer1", 0)),
            int(funnel.get("layer2", 0)),
            int(funnel.get("layer3", 0)),
            int(funnel.get("layer4", 0)),
            int(funnel.get("final", 0)),
        ))
        self.conn.commit()

    def get_screening_run(self, select_date: str) -> Optional[dict]:
        """Get the persisted funnel snapshot for a date, or None."""
        row = self.conn.execute(
            "SELECT * FROM screening_runs WHERE select_date = ?", (select_date,)
        ).fetchone()
        return dict(row) if row else None

    def save_signal(self, signal: dict) -> str:
        """Save a signal to database. Returns signal_id."""
        signal_id = signal.get("signal_id") or self._gen_signal_id(signal.get("signal_type", "buy"))
        trigger_time = signal.get("trigger_time") or now_cst().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute("""
            INSERT INTO signals (signal_id, signal_type, etf_code, etf_name, trigger_time,
                trigger_details, price, change_pct, suggested_amount, factor_summary,
                sell_strategy, sell_priority, sell_action, pnl_amount, pnl_pct, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal_id, signal.get("signal_type"), signal.get("etf_code"),
            signal.get("etf_name"), trigger_time,
            json.dumps(signal.get("trigger_details", {}), ensure_ascii=False),
            signal.get("price"), signal.get("change_pct"),
            signal.get("suggested_amount"),
            json.dumps(signal.get("factor_summary", {}), ensure_ascii=False),
            signal.get("sell_strategy"), signal.get("sell_priority"),
            signal.get("sell_action"), signal.get("pnl_amount"),
            signal.get("pnl_pct"), signal.get("status", "pending")
        ))
        self.conn.commit()
        return signal_id

    def get_signals(self, signal_type: Optional[str] = None, status: Optional[str] = None,
                     limit: int = 50) -> list[dict]:
        """Get signals with optional filters."""
        query = "SELECT * FROM signals WHERE 1=1"
        params = []
        if signal_type:
            query += " AND signal_type = ?"
            params.append(signal_type)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_pending_signals(self, signal_type: str = "buy") -> list[dict]:
        """Get pending signals of a type."""
        return self.get_signals(signal_type=signal_type, status="pending")

    def has_pending_sell_signal(self, etf_code: str, strategy_type: str) -> bool:
        """Check if there is already a pending sell signal for this ETF+strategy today.

        Used to de-duplicate sell signals emitted by the realtime daemon.
        """
        today = now_cst().strftime("%Y-%m-%d")
        row = self.conn.execute("""
            SELECT 1 FROM signals
            WHERE signal_type='sell' AND etf_code=? AND sell_strategy=? AND status='pending'
              AND date(trigger_time)=?
            LIMIT 1
        """, (etf_code, strategy_type, today)).fetchone()
        return row is not None

    def update_signal_status(self, signal_id: str, status: str,
                              extra: Optional[dict] = None,
                              commit: bool = True) -> bool:
        """Update signal status (confirmed/skipped/executed).

        commit=False 时交由调用方统一提交（用于建仓事务）。
        """
        if extra:
            sets = ", ".join([f"{k}=?" for k in extra.keys()])
            vals = list(extra.values()) + [status, signal_id]
            self.conn.execute(
                f"UPDATE signals SET {sets}, status=?, updated_at=datetime('now','localtime') WHERE signal_id=?",
                vals
            )
        else:
            self.conn.execute(
                "UPDATE signals SET status=?, updated_at=datetime('now','localtime') WHERE signal_id=?",
                (status, signal_id)
            )
        if commit:
            self.conn.commit()
        return True

    def save_position(self, pos: dict, commit: bool = True) -> int:
        """Save a new position. Returns position ID.

        commit=False 时交由调用方统一提交（用于建仓事务）。
        """
        cursor = self.conn.execute("""
            INSERT INTO positions (etf_code, etf_name, buy_signal_id, buy_date, buy_price,
                buy_amount, buy_shares, current_price, current_value, pnl_amount, pnl_pct,
                hold_days, is_trend_stock, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pos["etf_code"], pos["etf_name"], pos.get("buy_signal_id"),
            pos["buy_date"], pos["buy_price"], pos["buy_amount"], pos["buy_shares"],
            pos.get("current_price", pos["buy_price"]),
            pos.get("current_value", pos["buy_amount"]),
            0, 0, 0, int(pos.get("is_trend_stock", False)), "holding"
        ))
        if commit:
            self.conn.commit()
        return cursor.lastrowid

    def has_open_position(self, etf_code: str) -> bool:
        """是否存在同一 ETF 的持仓中（holding）记录。用于防止重复开仓。"""
        row = self.conn.execute(
            "SELECT 1 FROM positions WHERE etf_code=? AND status='holding' LIMIT 1",
            (etf_code,)
        ).fetchone()
        return row is not None

    def get_positions(self, status: Optional[str] = None) -> list[dict]:
        """Get positions with optional status filter."""
        query = "SELECT * FROM positions WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY buy_date DESC"
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_holding_positions(self) -> list[dict]:
        """Get all currently holding positions."""
        return self.get_positions(status="holding")

    def update_position_pnl(self, pos_id: int, current_price: float,
                            current_value: float, pnl_amount: float,
                            pnl_pct: float, hold_days: int,
                            is_trend_stock: bool, commit: bool = True) -> None:
        """Update position with latest PnL data.

        commit=False 时交由调用方统一提交（用于建仓事务）。
        """
        self.conn.execute("""
            UPDATE positions SET current_price=?, current_value=?, pnl_amount=?,
                pnl_pct=?, hold_days=?, is_trend_stock=?,
                updated_at=datetime('now','localtime')
            WHERE id=?
        """, (current_price, current_value, pnl_amount, pnl_pct, hold_days,
              int(is_trend_stock), pos_id))
        if commit:
            self.conn.commit()

    def close_position(self, pos_id: int, sell_price: float, sell_date: str,
                       sell_strategy: str, commit: bool = True) -> dict:
        """Close a position. Returns closed position data.

        commit=False 时交由调用方统一提交（用于平仓事务）。
        """
        pos = self.conn.execute("SELECT * FROM positions WHERE id=?", (pos_id,)).fetchone()
        if not pos:
            return {}
        pos = dict(pos)
        sell_pnl_amount = (sell_price - pos["buy_price"]) * pos["buy_shares"]
        sell_pnl_pct = (sell_price / pos["buy_price"] - 1) * 100

        self.conn.execute("""
            UPDATE positions SET status='sold', sell_date=?, sell_price=?,
                sell_pnl_amount=?, sell_pnl_pct=?, sell_strategy=?,
                updated_at=datetime('now','localtime')
            WHERE id=?
        """, (sell_date, sell_price, sell_pnl_amount, sell_pnl_pct, sell_strategy, pos_id))
        if commit:
            self.conn.commit()

        return {**pos, "sell_price": sell_price, "sell_date": sell_date,
                "sell_pnl_amount": sell_pnl_amount, "sell_pnl_pct": sell_pnl_pct,
                "sell_strategy": sell_strategy}

    def partial_sell_position(self, pos_id: int, sell_price: float, ratio: float,
                               sell_date: str, sell_strategy: str,
                               current_price: Optional[float] = None,
                               commit: bool = True) -> dict:
        """Sell a fraction (``ratio`` of shares) of a HOLD position.

        Unlike ``close_position`` (which clears the whole row and sets
        status='sold'), this keeps the position open (status stays
        'holding') and only reduces shares / cost basis proportionally,
        realizing PnL on the sold slice. This is what makes
        ``REDUCE_*`` sell actions actually *execute* instead of being
        recorded-and-ignored.

        Returns the updated (still-open) position dict, or ``{}`` if the
        position is missing or the computed share count to sell is zero.
        If ``ratio`` would sell the entire position, it degrades to a
        full ``close_position``.
        """
        pos = self.conn.execute("SELECT * FROM positions WHERE id=?", (pos_id,)).fetchone()
        if not pos:
            return {}
        pos = dict(pos)
        buy_price = pos["buy_price"]
        buy_shares = pos["buy_shares"]

        shares_to_sell = int(math.floor(buy_shares * ratio))
        if shares_to_sell <= 0:
            return {}

        remaining = buy_shares - shares_to_sell
        if remaining <= 0:
            # 比例过大 → 退化为清仓，保持语义一致
            return self.close_position(pos_id, sell_price, sell_date, sell_strategy, commit)

        realized_amount = sell_price * shares_to_sell
        realized_pnl_amount = (sell_price - buy_price) * shares_to_sell
        realized_pnl_pct = (sell_price / buy_price - 1) * 100 if buy_price else 0

        new_buy_amount = buy_price * remaining
        new_current_price = current_price if current_price is not None else sell_price
        new_current_value = new_current_price * remaining

        self.conn.execute("""
            UPDATE positions SET buy_amount=?, buy_shares=?, current_price=?,
                current_value=?, updated_at=datetime('now','localtime')
            WHERE id=?
        """, (new_buy_amount, remaining, new_current_price, new_current_value, pos_id))
        if commit:
            self.conn.commit()

        return {**pos, "shares_to_sell": shares_to_sell,
                "remaining_shares": remaining,
                "realized_amount": round(realized_amount, 2),
                "realized_pnl_amount": round(realized_pnl_amount, 2),
                "realized_pnl_pct": round(realized_pnl_pct, 2),
                "sell_price": sell_price, "sell_date": sell_date,
                "sell_strategy": sell_strategy}

    def mark_sell_signal_executed(self, etf_code: str, sell_action: str,
                                  realized_pnl_amount: float,
                                  realized_pnl_pct: float,
                                  commit: bool = True) -> None:
        """Mark the pending REDUCE sell signal for an ETF+action as executed.

        Matches on ``sell_action`` (the reduce action actually executed, e.g.
        ``REDUCE_50``) rather than ``sell_strategy`` (the Chinese strategy
        category). This keeps the UI contract (English action) and the signal
        stored by the sell engine (English action after the enum fix) aligned,
        so the pending signal is truly consumed instead of lingering as pending.
        """
        self.conn.execute("""
            UPDATE signals SET status='executed',
                pnl_amount=?, pnl_pct=?,
                updated_at=datetime('now','localtime')
            WHERE etf_code=? AND sell_action=? AND status='pending'
        """, (round(realized_pnl_amount, 2), round(realized_pnl_pct, 2),
              etf_code, sell_action))
        if commit:
            self.conn.commit()

    def get_closed_positions(self) -> list[dict]:
        """Get all closed (sold) positions for performance stats."""
        return self.get_positions(status="sold")

    # ---------- Pending Buy Pool ----------
    def get_pool_row(self, etf_code: str) -> Optional[dict]:
        """Get a single pending-buy-pool row by ETF code (or None)."""
        row = self.conn.execute(
            "SELECT * FROM pending_buy_pool WHERE etf_code=?", (etf_code,)
        ).fetchone()
        return dict(row) if row else None

    def get_pending_pool(self, status: Optional[str] = None) -> list[dict]:
        """Get pending-buy-pool rows, optionally filtered by status."""
        q = "SELECT * FROM pending_buy_pool WHERE 1=1"
        p: list = []
        if status:
            q += " AND status=?"
            p.append(status)
        q += " ORDER BY enter_time DESC"
        return [dict(r) for r in self.conn.execute(q, p).fetchall()]

    def add_to_pool(self, etf_code: str, etf_name: str,
                    entry_price: float, enter_time: str) -> bool:
        """Auto-add an ETF to the pending-buy pool.

        Returns False if a row already exists (incl. a 'sold' blacklist row),
        so ETFs marked sold by the sell-scan won't re-enter until manually removed.
        """
        if self.get_pool_row(etf_code):
            return False
        self.conn.execute(
            "INSERT INTO pending_buy_pool (etf_code, etf_name, entry_price, enter_time, status) "
            "VALUES (?, ?, ?, ?, 'watching')",
            (etf_code, etf_name, entry_price, enter_time),
        )
        self.conn.commit()
        return True

    def mark_pool_sold(self, etf_code: str, sell_price: float,
                        sell_time: str, pnl_pct: float) -> bool:
        """Mark a pool item as sold by the sell-scan (keeps row until manual remove)."""
        if not self.get_pool_row(etf_code):
            return False
        self.conn.execute(
            "UPDATE pending_buy_pool SET status='sold', sell_price=?, sell_time=?, "
            "pnl_pct=?, updated_at=datetime('now','localtime') WHERE etf_code=?",
            (sell_price, sell_time, pnl_pct, etf_code),
        )
        self.conn.commit()
        return True

    def remove_from_pool(self, etf_code: str) -> bool:
        """Manual remove from pool (watching or sold)."""
        cur = self.conn.execute(
            "DELETE FROM pending_buy_pool WHERE etf_code=?", (etf_code,)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def get_pool_sold_codes(self) -> set:
        """Codes currently blacklisted (marked sold) in the pool."""
        rows = self.conn.execute(
            "SELECT etf_code FROM pending_buy_pool WHERE status='sold'"
        ).fetchall()
        return {r["etf_code"] for r in rows}

    def get_strategy_params(self) -> list[dict]:
        """Get all strategy parameters."""
        rows = self.conn.execute("SELECT * FROM strategy_params ORDER BY param_group").fetchall()
        return [dict(r) for r in rows]

    def get_param(self, key: str) -> Optional[str]:
        """Get a single parameter value."""
        row = self.conn.execute(
            "SELECT param_value FROM strategy_params WHERE param_key=?", (key,)
        ).fetchone()
        return row["param_value"] if row else None

    def set_param(self, key: str, value: str, group: str, desc: str = "") -> None:
        """Set a parameter value, logging the change.

        写入 strategy_params 表后，同步回写到内存中的 config.settings 单例，
        使 buy/sell/screening 引擎在后续运行中立即采用新值（修 P0-1）。
        因子权重/选股类参数变更会使当日推荐缓存失效，下一轮扫描自动重算。
        """
        old = self.get_param(key)
        if old != value:
            self.conn.execute("""
                INSERT INTO param_change_log (param_key, old_value, new_value)
                VALUES (?, ?, ?)
            """, (key, old or "", value))
        self.conn.execute("""
            INSERT INTO strategy_params (param_key, param_value, param_group, description)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(param_key) DO UPDATE SET param_value=?, updated_at=datetime('now','localtime')
        """, (key, value, group, desc, value))
        self.conn.commit()
        # 关键修复：把参数同步到引擎实际读取的 config.settings 单例（带类型强转）
        self._apply_param_to_settings(key, value)
        # 因子权重/选股类参数影响当日推荐结果，立即使缓存失效以触发重算
        if group in ("screening", "factor"):
            self._invalidate_screening_cache()

    def _apply_param_to_settings(self, key: str, value: str) -> None:
        """Push a DB strategy param into the live ``config.settings`` singleton.

        引擎（buy/sell/screening）运行时读取 ``config.settings`` 而非数据库，
        因此仅写库不会让调参生效；这里把参数同步到内存单例并做类型强转。
        """
        attr = key.upper()
        if not hasattr(settings, attr):
            return
        current = getattr(settings, attr)
        try:
            if isinstance(current, bool):
                new_val = str(value).strip().lower() in ("1", "true", "yes", "on")
            elif isinstance(current, int):
                new_val = int(round(float(value)))
            elif isinstance(current, float):
                new_val = float(value)
            else:
                new_val = value
        except (ValueError, TypeError):
            return
        setattr(settings, attr, new_val)

    def _invalidate_screening_cache(self) -> None:
        """Flush cached today-recommendations so the next scan picks up new params."""
        try:
            from src.screening.screening_engine import get_screening
            get_screening().invalidate_cache()
        except Exception:
            pass

    def load_params_into_settings(self) -> None:
        """Load all strategy_params rows into the live config.settings (call once at startup)."""
        for p in self.get_strategy_params():
            self._apply_param_to_settings(p["param_key"], p["param_value"])

    def init_default_params(self) -> None:
        """Initialize default strategy parameters in database."""
        defaults = [
            ("daily_select_count", "2", "screening", "每日选股数量"),
            ("momentum_period", "20", "screening", "动量计算周期"),
            ("liquidity_threshold", "3000", "screening", "流动性门槛（万元）"),
            ("market_cap_threshold", "80", "screening", "总市值门槛（亿元）"),
            ("market_drop_threshold", "-2", "screening", "沪深300日跌幅空仓信号阈值"),
            ("weight_trend", "0.25", "factor", "趋势强度权重"),
            ("weight_momentum", "0.20", "factor", "动量得分权重"),
            ("weight_volume", "0.15", "factor", "量能指标权重"),
            ("weight_volatility", "0.10", "factor", "波动率权重"),
            ("weight_technical", "0.30", "factor", "其他技术指标权重"),
            ("buy_ma5_tolerance", "0.015", "buy", "MA5回踩容忍度"),
            ("buy_volume_surge_mult", "2.0", "buy", "主力资金异动倍数"),
            ("buy_volume_ratio", "1.5", "buy", "当日量/5日均量倍数"),
            ("high_open_threshold", "2.0", "sell", "高开幅度阈值"),
            ("high_open_drop_threshold", "-0.8", "sell", "高开后回调阈值"),
            ("take_profit_threshold", "30", "sell", "止盈阈值"),
            ("take_profit_step", "10", "sell", "阶梯止盈步长"),
            ("stop_loss_base", "-6", "sell", "基础止损"),
            ("stop_loss_relaxed", "-7.2", "sell", "持仓<5天放宽止损"),
            ("stop_loss_tightened", "-5.4", "sell", "持仓>10天收紧止损"),
            ("peak_reversal_rise", "2.6", "sell", "冲高回落日涨幅阈值"),
            ("mandatory_rise", "3.5", "sell", "强制减仓涨幅阈值"),
            ("adx_threshold", "25", "sell", "ADX趋势动力阈值"),
            ("total_capital", "100000", "screening", "总资金（元）"),
            ("single_position_limit", "0.30", "screening", "单只ETF仓位上限"),
            ("total_position_limit", "0.80", "screening", "总仓位上限"),
        ]
        for key, value, group, desc in defaults:
            existing = self.get_param(key)
            if existing is None:
                self.conn.execute("""
                    INSERT INTO strategy_params (param_key, param_value, param_group, description)
                    VALUES (?, ?, ?, ?)
                """, (key, value, group, desc))
        self.conn.commit()

    def _gen_signal_id(self, signal_type: str) -> str:
        """Generate a unique signal ID."""
        prefix = "BUY" if signal_type == "buy" else "SELL" if signal_type == "sell" else "EMPTY"
        today = now_cst().strftime("%Y%m%d")
        count = self.conn.execute(
            "SELECT COUNT(*) as c FROM signals WHERE signal_id LIKE ?",
            (f"{prefix}-{today}-%",)
        ).fetchone()
        seq = (count["c"] if count else 0) + 1
        return f"{prefix}-{today}-{seq:02d}"

    def get_pool_sync_logs(self, limit: int = 10) -> list[dict]:
        """Get pool sync logs."""
        rows = self.conn.execute(
            "SELECT * FROM pool_sync_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_performance_stats(self) -> dict:
        """Calculate performance statistics from closed positions."""
        closed = self.get_closed_positions()
        if not closed:
            return {
                "total_trades": 0, "win_count": 0, "loss_count": 0,
                "win_rate": 0, "total_pnl": 0, "avg_profit": 0,
                "avg_loss": 0, "profit_loss_ratio": 0,
                "max_profit": 0, "max_loss": 0,
                "max_consecutive_losses": 0,
            }

        wins = [t for t in closed if (t.get("sell_pnl_amount") or 0) > 0]
        losses = [t for t in closed if (t.get("sell_pnl_amount") or 0) <= 0]
        total_pnl = sum(t.get("sell_pnl_amount", 0) for t in closed)
        win_pnls = [t["sell_pnl_amount"] for t in wins]
        loss_pnls = [t["sell_pnl_amount"] for t in losses]

        # Max consecutive losses
        max_consec = 0
        current_consec = 0
        for t in closed:
            if (t.get("sell_pnl_amount") or 0) <= 0:
                current_consec += 1
                max_consec = max(max_consec, current_consec)
            else:
                current_consec = 0

        return {
            "total_trades": len(closed),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_profit": round(sum(win_pnls) / len(win_pnls), 2) if win_pnls else 0,
            "avg_loss": round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else 0,
            "profit_loss_ratio": round(abs(sum(win_pnls) / len(win_pnls)) / abs(sum(loss_pnls) / len(loss_pnls)), 2) if win_pnls and loss_pnls else 0,
            "max_profit": round(max(win_pnls), 2) if win_pnls else 0,
            "max_loss": round(min(loss_pnls), 2) if loss_pnls else 0,
            "max_consecutive_losses": max_consec,
        }


def get_connection():
    """Get database connection (imported from database module)."""
    from database import get_connection as _get_conn
    return _get_conn()
