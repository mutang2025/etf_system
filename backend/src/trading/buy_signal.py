"""Buy signal detection engine.

Three buy conditions must be simultaneously satisfied:
1. Price near MA5 (within ±1.5%)
2. Main capital surge (5-min volume >= 2x 5-day avg minute volume)
3. Daily volume >= 1.5x 5-day average volume
"""

from datetime import datetime
from typing import Optional
import numpy as np

from src.domain.entities import BuySignal
from src.infrastructure.data_provider_factory import get_data_provider
from src.infrastructure.indicator_cache import (
    get_cached_indicators,
    DEFAULT_INDICATOR_DAYS,
)
from src.infrastructure.timeutil import now_cst
from config import settings


class BuySignalEngine:
    """Detects buy signals by checking three simultaneous conditions."""

    def __init__(self, data_provider=None):
        self.mock = data_provider or get_data_provider()
        self._condition_hold: dict[str, int] = {}  # etf_code -> seconds condition held

    def check_buy_conditions(self, etf_code: str) -> tuple[bool, dict]:
        """Check if all three buy conditions are met for an ETF.

        Returns (is_triggered, condition_details).
        """
        klines = self.mock.get_klines(etf_code, DEFAULT_INDICATOR_DAYS)
        if len(klines) < 10:
            return False, {"error": "insufficient data"}

        # Get latest realtime quote
        rt = self.mock.get_realtime_quote(etf_code)
        if not rt:
            return False, {"error": "no realtime data"}

        # Cached indicators — recomputed only when a new daily bar lands
        indicators = get_cached_indicators(self.mock, etf_code, DEFAULT_INDICATOR_DAYS)

        # Condition 1: Price near MA5 (within ±1.5%)
        ma5 = indicators["MA"].get("MA5")
        current_price = rt["price"]
        if ma5 is None or ma5 == 0:
            cond1 = False
            cond1_detail = "MA5数据不足"
        else:
            deviation = abs(current_price - ma5) / ma5
            cond1 = deviation <= settings.BUY_MA5_TOLERANCE
            cond1_detail = f"当前价{current_price:.4f} vs MA5={ma5:.4f}，偏离{deviation*100:.2f}%（阈值{settings.BUY_MA5_TOLERANCE*100}%）"

        # Condition 2: 主力资金异动（量能异动）
        # MVP 无分时tick数据，改用真实量比判定：实时量比 >= BUY_VOLUME_SURGE_MULT(2.0)。
        # 实时量比由数据源提供（mock 下基于该ETF近20日量能比确定性生成），
        # 不再使用随机因子模拟，保证信号可解释、可复现。
        recent_volumes = [k.volume for k in klines[-5:]]
        avg_5d_vol = np.mean(recent_volumes) if recent_volumes else 0
        current_vol = rt.get("volume", 0)

        if avg_5d_vol > 0:
            rt_volume_ratio = rt.get("volume_ratio", 0)
            # 实时量比缺失时用当日成交量/5日均量兜底
            computed_ratio = current_vol / avg_5d_vol if current_vol > 0 else 0
            effective_ratio = rt_volume_ratio if (rt_volume_ratio and rt_volume_ratio > 0) else computed_ratio
            cond2 = effective_ratio >= settings.BUY_VOLUME_SURGE_MULT
            cond2_detail = f"主力资金异动：量比{effective_ratio:.2f}（阈值{settings.BUY_VOLUME_SURGE_MULT}）"
        else:
            cond2 = False
            cond2_detail = "成交量数据不足"

        # Condition 3: Daily volume >= 1.5x 5-day average volume
        if avg_5d_vol > 0:
            vol_ratio = current_vol / avg_5d_vol
            cond3 = vol_ratio >= settings.BUY_VOLUME_RATIO
            cond3_detail = f"当日量比{vol_ratio:.2f}（阈值{settings.BUY_VOLUME_RATIO}）"
        else:
            cond3 = False
            cond3_detail = "成交量数据不足"

        all_met = cond1 and cond2 and cond3

        # Track condition hold time (anti-flicker: must hold >= 10 seconds)
        if all_met:
            self._condition_hold[etf_code] = self._condition_hold.get(etf_code, 0) + 10
        else:
            self._condition_hold[etf_code] = 0

        details = {
            "condition1": {"name": "价格回踩5日均线", "passed": cond1, "detail": cond1_detail},
            "condition2": {"name": "分时图主力资金异动", "passed": cond2, "detail": cond2_detail},
            "condition3": {"name": "当日成交量放大", "passed": cond3, "detail": cond3_detail},
            "all_met": all_met,
            "hold_seconds": self._condition_hold.get(etf_code, 0),
        }

        return all_met, details

    def generate_buy_signal(self, etf_code: str, etf_name: str,
                           factor_summary: dict,
                           available_capital: Optional[float] = None) -> Optional[BuySignal]:
        """Generate a buy signal for an ETF that passed all conditions.

        available_capital: 可用资金（总资金 - 已持仓投入）。提供后，建议买入金额
        受单只上限与总仓位上限双重约束（修复 P1-1：原实现恒为 30% 且不扣已持仓）。
        """
        rt = self.mock.get_realtime_quote(etf_code)
        if not rt:
            return None

        now = now_cst()
        signal_id = f"BUY-{now.strftime('%Y%m%d')}-{len(self._condition_hold):02d}"

        # 建议买入金额：受单只上限 + 总仓位上限约束，并扣除已持仓
        if available_capital is not None:
            single_cap = settings.TOTAL_CAPITAL * settings.SINGLE_POSITION_LIMIT
            invested = settings.TOTAL_CAPITAL - available_capital
            total_room = settings.TOTAL_CAPITAL * settings.TOTAL_POSITION_LIMIT - invested
            suggested_amount = min(single_cap, total_room, available_capital)
            suggested_amount = max(suggested_amount, 0.0)
        else:
            suggested_amount = settings.TOTAL_CAPITAL * settings.SINGLE_POSITION_LIMIT

        signal = BuySignal(
            signal_id=signal_id,
            etf_code=etf_code,
            etf_name=etf_name,
            trigger_time=now.strftime("%Y-%m-%d %H:%M:%S"),
            price=rt["price"],
            change_pct=rt["change_pct"],
            suggested_amount=round(suggested_amount, 2),
            trigger_details=self.check_buy_conditions(etf_code)[1],
            factor_summary=factor_summary,
            status="pending",
        )
        return signal

    def scan_candidates(self, candidate_codes: list[str],
                       factor_map: dict = None,
                       available_capital: Optional[float] = None) -> list[BuySignal]:
        """Scan all candidate ETFs for buy conditions.

        Args:
            candidate_codes: ETF codes from screening engine's final recommendations.
            factor_map: Optional dict of etf_code -> factor summary for signal enrichment.
            available_capital: 可用资金，用于建议金额的总仓位上限约束。
        """
        signals: list[BuySignal] = []
        for code in candidate_codes:
            triggered, details = self.check_buy_conditions(code)
            if triggered:
                etf = None
                for e in self.mock.get_etf_pool():
                    if e.code == code:
                        etf = e
                        break
                if not etf:
                    continue
                factor_summary = (factor_map or {}).get(code, {})
                signal = self.generate_buy_signal(
                    code, etf.name, factor_summary, available_capital
                )
                if signal:
                    signal.trigger_details = details
                    signals.append(signal)
        return signals

    def is_in_cooldown(self, etf_code: str, sold_dates: dict) -> bool:
        """Check if an ETF is in sell cooldown period.

        Args:
            etf_code: ETF code to check.
            sold_dates: dict of etf_code -> last sell date string.
        """
        if etf_code not in sold_dates:
            return False
        last_sell = sold_dates[etf_code]
        try:
            sell_dt = datetime.strptime(last_sell, "%Y-%m-%d").date()
            days_since = (now_cst().date() - sell_dt).days
            return days_since < settings.SELL_COOLDOWN_DAYS
        except (ValueError, TypeError):
            return False
