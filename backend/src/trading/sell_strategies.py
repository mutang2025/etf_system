"""Seven sell strategies with priority-based arbitration.

Priority hierarchy (100 highest, 65 lowest):
100 - Emergency Circuit Breaker (紧急熔断)
 90 - High-open Dump (高开砸盘)
 85 - Danger Signal (危险信号)
 80 - Trend Analysis (趋势分析)
 75 - Take Profit / Stop Loss (止盈止损)
 70 - Peak Reversal (冲高回落)
 65 - Mandatory Reduction (强制减仓)
"""

from datetime import datetime, timedelta
from typing import Optional
import numpy as np

from src.domain.entities import SellSignal, Position
from src.domain.enums import SellStrategyType, SellAction
from src.indicators.technical import IndicatorCalculator, sma, is_uptrend_arrangement
from src.infrastructure.data_provider_factory import get_data_provider
from config import settings


class SellStrategyEngine:
    """7 sell strategies with priority arbitration."""

    def __init__(self, data_provider=None):
        self.mock = data_provider or get_data_provider()
        self._peak_tracker: dict[str, float] = {}  # etf_code -> today's peak gain
        self._no_new_high_tracker: dict[str, int] = {}  # etf_code -> minutes since new high

    def check_all_strategies(self, position: dict) -> Optional[SellSignal]:
        """Check all 7 sell strategies for a position. Returns highest priority triggered signal.

        Position dict must contain: etf_code, etf_name, buy_price, buy_shares,
        buy_date, hold_days, is_trend_stock, current_price.
        """
        etf_code = position["etf_code"]
        current_price = position.get("current_price", 0)
        buy_price = position["buy_price"]
        buy_shares = position.get("buy_shares", 0)
        hold_days = position.get("hold_days", 0)
        is_trend = bool(position.get("is_trend_stock", False))

        # Calculate PnL
        pnl_pct = (current_price / buy_price - 1) * 100 if buy_price else 0
        pnl_amount = (current_price - buy_price) * buy_shares

        # Get indicators
        klines = self.mock.get_klines(etf_code, 120)
        indicators = {}
        if klines and len(klines) >= 30:
            calc = IndicatorCalculator(klines)
            indicators = calc.get_all_indicators()

        # Get realtime
        rt = self.mock.get_realtime_quote(etf_code)
        today_change = rt["change_pct"] if rt else 0
        current_time = datetime.now()

        # Check all strategies in priority order (highest first)
        # Each returns (triggered, detail, action)
        checks = [
            self._check_emergency_circuit(position, pnl_pct, pnl_amount),
            self._check_high_open_dump(position, today_change, indicators, current_time),
            self._check_danger_signal(position, indicators),
            self._check_trend_analysis(position, indicators),
            self._check_take_profit_stop_loss(position, pnl_pct, hold_days),
            self._check_peak_reversal(position, today_change, current_time),
            self._check_mandatory_reduction(position, today_change, current_time),
        ]

        for triggered, strategy_type, priority, action, detail in checks:
            if triggered:
                return SellSignal(
                    signal_id=f"SELL-{current_time.strftime('%Y%m%d')}-{etf_code[-6:]}",
                    etf_code=etf_code,
                    etf_name=position.get("etf_name", ""),
                    trigger_time=current_time.strftime("%Y-%m-%d %H:%M:%S"),
                    strategy_type=strategy_type,
                    priority=priority,
                    price=current_price,
                    buy_price=buy_price,
                    pnl_amount=round(pnl_amount, 2),
                    pnl_pct=round(pnl_pct, 2),
                    action=action,
                    hold_days=hold_days,
                    status="pending",
                )

        return None

    def _check_emergency_circuit(self, pos: dict, pnl_pct: float,
                                  pnl_amount: float) -> tuple:
        """Priority 100: Emergency Circuit Breaker.

        Triggers when: system abnormality, consecutive losses, or total floating loss > 5%.
        """
        if pnl_pct <= settings.EMERGENCY_LOSS_THRESHOLD:
            return (True, SellStrategyType.EMERGENCY_CIRCUIT.value, 100,
                    SellAction.CLEAR_ALL.value,
                    f"持仓浮亏{pnl_pct:.2f}%超过紧急熔断阈值{settings.EMERGENCY_LOSS_THRESHOLD}%，立即清仓保全本金")
        return (False, "", 0, "", "")

    def _check_high_open_dump(self, pos: dict, today_change: float,
                               indicators: dict, now: datetime) -> tuple:
        """Priority 90: High-open Dump.

        Triggers when: 9:30-10:30, opened high >2%, then dropped >0.8%, not in uptrend.
        """
        # Check time window: 9:30-10:30
        if not (now.hour == 9 and now.minute >= 30) or (now.hour == 10 and now.minute <= 30):
            if not (9 <= now.hour <= 10):
                return (False, "", 0, "", "")
            if now.hour == 9 and now.minute < 30:
                return (False, "", 0, "", "")

        # Check if not in uptrend
        is_up = indicators.get("is_uptrend_arrangement", False)
        if is_up:
            return (False, "", 0, "", "")

        # Check high open and drop
        # Simulate: if today's change was initially high but now dropping
        # We use the realtime change as a proxy
        rt = self.mock.get_realtime_quote(pos["etf_code"])
        if not rt:
            return (False, "", 0, "", "")

        open_price = rt.get("open", 0)
        prev_close = rt.get("prev_close", 0)
        current = rt.get("price", 0)

        if prev_close == 0:
            return (False, "", 0, "", "")

        high_open_pct = (open_price / prev_close - 1) * 100
        drop_from_open = (current / open_price - 1) * 100

        if high_open_pct > settings.HIGH_OPEN_THRESHOLD and drop_from_open < settings.HIGH_OPEN_DROP_THRESHOLD:
            return (True, SellStrategyType.HIGH_OPEN_DUMP.value, 90,
                    SellAction.CLEAR_ALL.value,
                    f"高开{high_open_pct:.2f}%后下跌{drop_from_open:.2f}%，非上升趋势，高开砸盘信号触发")

        return (False, "", 0, "", "")

    def _check_danger_signal(self, pos: dict, indicators: dict) -> tuple:
        """Priority 85: Danger Signal.

        Triggers when: five-fold death cross, volume-price divergence, or ADX danger.
        """
        death_cross = indicators.get("death_cross", False)
        vol_price_div = indicators.get("volume_price_divergence", False)
        adx_danger = indicators.get("adx_danger", False)

        signals = []
        if death_cross:
            signals.append("五重死叉")
        if vol_price_div:
            signals.append("日线量价背离")
        if adx_danger:
            signals.append("ADX趋势减弱")

        if signals:
            # If multiple signals, suggest clear all; if single, reduce 50%
            if len(signals) >= 2:
                action = SellAction.CLEAR_ALL.value
                detail = f"多重危险信号：{' + '.join(signals)}，建议清仓"
            else:
                action = SellAction.REDUCE_50.value
                detail = f"危险信号：{signals[0]}，建议减仓50%"
            return (True, SellStrategyType.DANGER_SIGNAL.value, 85, action, detail)

        return (False, "", 0, "", "")

    def _check_trend_analysis(self, pos: dict, indicators: dict) -> tuple:
        """Priority 80: Trend Analysis.

        For trend stocks: only sell when trend truly breaks (below MA20 for 3 days).
        For non-trend stocks: this strategy is less aggressive.
        """
        is_trend = bool(pos.get("is_trend_stock", False))
        if not is_trend:
            # Non-trend stock: skip this strategy, let others handle
            return (False, "", 0, "", "")

        trend_break = indicators.get("trend_break", False)
        if trend_break:
            return (True, SellStrategyType.TREND_ANALYSIS.value, 80,
                    SellAction.CLEAR_ALL.value,
                    "趋势股跌破20日均线且3日未收回，趋势反转确认，建议清仓")

        return (False, "", 0, "", "")

    def _check_take_profit_stop_loss(self, pos: dict, pnl_pct: float,
                                       hold_days: int) -> tuple:
        """Priority 75: Take Profit / Stop Loss.

        Take profit: >30% sell 1/3, +10% more sell half, +10% more clear all.
        Stop loss: base -6%, relaxed to -7.2% if <5 days, tightened to -5.4% if >10 days.
        """
        # Take profit check
        if pnl_pct >= settings.TAKE_PROFIT_THRESHOLD:
            step = int((pnl_pct - settings.TAKE_PROFIT_THRESHOLD) / settings.TAKE_PROFIT_STEP)
            if step == 0:
                return (True, SellStrategyType.TAKE_PROFIT_STOP_LOSS.value, 75,
                        SellAction.REDUCE_33.value,
                        f"浮盈{pnl_pct:.2f}%达到止盈阈值{settings.TAKE_PROFIT_THRESHOLD}%，建议卖出1/3仓位")
            elif step == 1:
                return (True, SellStrategyType.TAKE_PROFIT_STOP_LOSS.value, 75,
                        SellAction.REDUCE_HALF.value,
                        f"阶梯止盈：浮盈{pnl_pct:.2f}%，再涨{settings.TAKE_PROFIT_STEP}%，建议卖出剩余一半")
            else:
                return (True, SellStrategyType.TAKE_PROFIT_STOP_LOSS.value, 75,
                        SellAction.CLEAR_ALL.value,
                        f"阶梯止盈最终档：浮盈{pnl_pct:.2f}%，建议清仓")

        # Dynamic stop loss
        if hold_days < 5:
            stop_threshold = settings.STOP_LOSS_RELAXED
        elif hold_days > 10:
            stop_threshold = settings.STOP_LOSS_TIGHTENED
        else:
            stop_threshold = settings.STOP_LOSS_BASE

        if pnl_pct <= stop_threshold:
            return (True, SellStrategyType.TAKE_PROFIT_STOP_LOSS.value, 75,
                    SellAction.STOP_LOSS.value,
                    f"浮亏{pnl_pct:.2f}%触发止损线{stop_threshold}%（持仓{hold_days}天），建议立即止损")

        return (False, "", 0, "", "")

    def _check_peak_reversal(self, pos: dict, today_change: float,
                              now: datetime) -> tuple:
        """Priority 70: Peak Reversal.

        Triggers when: intraday gain > 2.6% then retreats.
        Retreat stages: 0.6% sell 1/3, 1.0% sell half, 1.5% clear all.
        """
        etf_code = pos["etf_code"]

        # Track peak gain
        if etf_code not in self._peak_tracker or self._peak_tracker[etf_code] < today_change:
            self._peak_tracker[etf_code] = today_change

        peak_gain = self._peak_tracker[etf_code]

        # Only trigger if peak was above threshold
        if peak_gain < settings.PEAK_REVERSAL_RISE:
            return (False, "", 0, "", "")

        # Calculate retreat from peak
        retreat = peak_gain - today_change

        if retreat >= settings.PEAK_REVERSAL_DROP_3:
            return (True, SellStrategyType.PEAK_REVERSAL.value, 70,
                    SellAction.CLEAR_ALL.value,
                    f"日内高点涨{peak_gain:.2f}%，回落{retreat:.2f}%≥{settings.PEAK_REVERSAL_DROP_3}%，建议清仓")
        elif retreat >= settings.PEAK_REVERSAL_DROP_2:
            return (True, SellStrategyType.PEAK_REVERSAL.value, 70,
                    SellAction.REDUCE_HALF.value,
                    f"日内高点涨{peak_gain:.2f}%，回落{retreat:.2f}%≥{settings.PEAK_REVERSAL_DROP_2}%，建议卖出剩余一半")
        elif retreat >= settings.PEAK_REVERSAL_DROP_1:
            return (True, SellStrategyType.PEAK_REVERSAL.value, 70,
                    SellAction.REDUCE_33.value,
                    f"日内高点涨{peak_gain:.2f}%，回落{retreat:.2f}%≥{settings.PEAK_REVERSAL_DROP_1}%，建议卖出1/3仓位")

        return (False, "", 0, "", "")

    def _check_mandatory_reduction(self, pos: dict, today_change: float,
                                     now: datetime) -> tuple:
        """Priority 65: Mandatory Reduction.

        Triggers when: gain > 3.5% and no new high in 5 minutes, not in 9:25-9:40 window.
        """
        # Avoid opening auction window
        if now.hour == 9 and now.minute >= 25 and now.minute <= 40:
            return (False, "", 0, "", "")

        if today_change < settings.MANDATORY_RISE:
            return (False, "", 0, "", "")

        etf_code = pos["etf_code"]

        # Track new high
        peak = self._peak_tracker.get(etf_code, today_change)
        if today_change >= peak:
            self._no_new_high_tracker[etf_code] = 0
            self._peak_tracker[etf_code] = today_change
        else:
            self._no_new_high_tracker[etf_code] = self._no_new_high_tracker.get(etf_code, 0) + 1

        minutes_no_high = self._no_new_high_tracker.get(etf_code, 0)

        if minutes_no_high >= settings.MANDATORY_NO_NEW_HIGH_MIN:
            return (True, SellStrategyType.MANDATORY_REDUCTION.value, 65,
                    SellAction.REDUCE_50.value,
                    f"涨幅{today_change:.2f}%≥{settings.MANDATORY_RISE}%且{minutes_no_high}分钟未创新高，建议卖出50%")

        return (False, "", 0, "", "")

    def reset_daily_trackers(self) -> None:
        """Reset daily tracking data (call at start of each trading day)."""
        self._peak_tracker.clear()
        self._no_new_high_tracker.clear()

    def check_all_positions(self, positions: list[dict]) -> list[SellSignal]:
        """Check all holding positions for sell signals. Returns list of triggered signals."""
        signals: list[SellSignal] = []
        for pos in positions:
            # Update current price from realtime
            rt = self.mock.get_realtime_quote(pos["etf_code"])
            if rt:
                pos["current_price"] = rt["price"]
            signal = self.check_all_strategies(pos)
            if signal:
                signals.append(signal)
        return signals
