"""回测卖出纪律：把实盘 7 条卖出策略搬到历史日 K 线。

设计原则（与「复用不复制」一致）：
- **指标计算**：直接复用 ``indicators/technical.py`` 的纯函数
  （``check_bearish_arrangement`` / ``check_volume_price_divergence`` /
  ``check_adx_danger`` / ``check_trend_break`` / ``is_uptrend_arrangement``），
  与实盘 ``IndicatorCalculator.get_all_indicators()`` 同源，绝不复制指标逻辑。
- **阈值 / 动作映射**：全部取自 ``config.settings``（``EMERGENCY_LOSS_THRESHOLD``、
  ``TAKE_PROFIT_*``、``STOP_LOSS_*``、``PEAK_REVERSAL_*``、``MANDATORY_*``…），
  与实盘 ``SellStrategyEngine`` 完全一致——保证「纪律本身」和实盘是同一套。
- **唯一差异（如实标注）**：实盘吃日内实时行情（``change_pct`` / ``open`` /
  ``prev_close`` + 分钟级峰值追踪），回测只有日 K。对依赖日内信息的
  P90 高开砸盘 / P70 冲高回落 / P65 强制减仓，用日 K 的
  ``open``/``high``/``low``/``close`` 做「日级近似」：

    * 当日涨幅 ``today_change``  = (close / prev_close - 1) * 100
    * 高开幅度 ``high_open_pct`` = (open / prev_close - 1) * 100
    * 日内峰值 ``peak_gain`` ≈ (high / prev_close - 1) * 100  （日 K 最高=当日峰值）
    * 回落 ``retreat`` = peak_gain - today_change
    * 强制减仓「未创新高」日级近似 = 当日收 ``close < high``（冲高后回落未守）
"""

from dataclasses import dataclass
from typing import Optional

from src.domain.entities import DailyKline
from src.domain.enums import SellStrategyType, SellAction, parse_reduce_ratio
from src.indicators.technical import (
    check_bearish_arrangement,
    check_volume_price_divergence,
    check_adx_danger,
    check_trend_break,
    is_uptrend_arrangement,
)
from config import settings


@dataclass
class SellDecision:
    """历史某日对某持仓的卖出纪律决议。"""

    triggered: bool
    strategy_type: str                 # SellStrategyType.value
    priority: int                      # 100(high) ~ 65(low)
    action: str                        # SellAction.value（英文契约）
    detail: str
    reduce_ratio: Optional[float] = None   # 仅 REDUCE_* 动作有意义


def compute_history_indicators(klines_upto: list[DailyKline]) -> dict:
    """复用实盘指标纯函数，从「截至今日的日 K 窗口」算 indicators。

    返回键与实盘 ``SellStrategyEngine`` 期望的完全一致
    （``death_cross`` / ``volume_price_divergence`` / ``adx_danger`` /
    ``trend_break`` / ``is_uptrend_arrangement`` 等），空窗或数据不足返回 ``{}``。
    """
    from src.indicators.technical import IndicatorCalculator

    return IndicatorCalculator(klines_upto).get_all_indicators()


def _daily_bar_inputs(klines_upto: list[DailyKline]) -> dict:
    """从日 K 末尾两根棒，导出卖出引擎需要的当日输入（日级近似）。

    长度不足 2 根时退化为「无信号」（today_change 等归零），纪律不触发——安全。
    """
    if len(klines_upto) < 1:
        return {
            "today_change": 0.0, "open": 0.0, "prev_close": 0.0,
            "close": 0.0, "high": 0.0, "low": 0.0,
            "high_open_pct": 0.0, "drop_from_open": 0.0, "peak_gain": 0.0,
        }
    today = klines_upto[-1]
    prev = klines_upto[-2] if len(klines_upto) >= 2 else today
    prev_close = prev.close
    close = today.close
    open_ = today.open
    high = today.high
    today_change = (close / prev_close - 1) * 100 if prev_close else 0.0
    high_open_pct = (open_ / prev_close - 1) * 100 if prev_close else 0.0
    drop_from_open = (close / open_ - 1) * 100 if open_ else 0.0
    peak_gain = (high / prev_close - 1) * 100 if prev_close else 0.0  # 日内峰值≈当日最高
    return {
        "today_change": today_change,
        "open": open_, "prev_close": prev_close, "close": close,
        "high": high, "low": today.low,
        "high_open_pct": high_open_pct,
        "drop_from_open": drop_from_open,
        "peak_gain": peak_gain,
    }


def historical_sell_check(position: dict, klines_upto: list[DailyKline],
                          portfolio_pnl_pct: float = 0.0,
                          indicators: Optional[dict] = None) -> SellDecision:
    """对单个持仓，在历史上某日跑 7 条纪律仲裁，返回是否触发及动作。

    ``position`` 需含：``etf_code`` / ``buy_price`` / ``buy_shares`` /
    ``buy_date`` / ``hold_days`` / ``is_trend_stock`` / ``current_price``
    （current_price 应为当日收盘价）。
    ``indicators`` 可预计算注入（实现层复用缓存，避免每持仓每日重算）；
    为 ``None`` 时自行从 ``klines_upto`` 算。
    """
    etf_code = position["etf_code"]
    buy_price = position["buy_price"]
    buy_shares = position.get("buy_shares", 0)
    hold_days = position.get("hold_days", 0)
    is_trend = bool(position.get("is_trend_stock", False))
    current_price = position.get("current_price", 0)
    pnl_pct = (current_price / buy_price - 1) * 100 if buy_price else 0.0
    pnl_amount = (current_price - buy_price) * buy_shares

    if indicators is None:
        indicators = compute_history_indicators(klines_upto)
    bar = _daily_bar_inputs(klines_upto)

    checks = [
        _check_emergency_circuit(position, pnl_pct, pnl_amount, portfolio_pnl_pct),
        _check_high_open_dump(position, bar, indicators),
        _check_danger_signal(position, indicators),
        _check_trend_analysis(position, indicators),
        _check_take_profit_stop_loss(position, pnl_pct, hold_days),
        _check_peak_reversal(position, bar),
        _check_mandatory_reduction(position, bar),
    ]
    for triggered, strategy_type, priority, action, detail in checks:
        if triggered:
            return SellDecision(
                triggered=True, strategy_type=strategy_type, priority=priority,
                action=action, detail=detail,
                reduce_ratio=parse_reduce_ratio(action),
            )
    return SellDecision(
        triggered=False, strategy_type="", priority=0, action="", detail=""
    )


# --------------------------------------------------------------------------
# 7 条纪律检查（阈值 / 动作映射与实盘 SellStrategyEngine 一致，
#   仅日内输入换成 _daily_bar_inputs 的日级近似值）
# --------------------------------------------------------------------------
def _check_emergency_circuit(pos: dict, pnl_pct: float, pnl_amount: float,
                              portfolio_pnl_pct: float = 0.0) -> tuple:
    """Priority 100：紧急熔断（组合/单笔浮亏超阈值即清仓）。"""
    if portfolio_pnl_pct <= settings.EMERGENCY_LOSS_THRESHOLD:
        return (True, SellStrategyType.EMERGENCY_CIRCUIT.value, 100,
                SellAction.CLEAR_ALL.value,
                f"整体组合浮亏{portfolio_pnl_pct:.2f}%超过紧急熔断阈值"
                f"{settings.EMERGENCY_LOSS_THRESHOLD}%，立即清仓保全本金")
    if pnl_pct <= settings.EMERGENCY_LOSS_THRESHOLD:
        return (True, SellStrategyType.EMERGENCY_CIRCUIT.value, 100,
                SellAction.CLEAR_ALL.value,
                f"持仓{pos.get('etf_code', '')}浮亏{pnl_pct:.2f}%触及紧急止损线，立即清仓")
    return (False, "", 0, "", "")


def _check_high_open_dump(pos: dict, bar: dict, indicators: dict) -> tuple:
    """Priority 90：高开砸盘（日级近似：去掉 9:30-10:30 时间窗，
    直接用当日 open/prev_close/close 判定）。"""
    is_up = indicators.get("is_uptrend_arrangement", False)
    if is_up:
        return (False, "", 0, "", "")
    high_open_pct = bar["high_open_pct"]
    drop_from_open = bar["drop_from_open"]
    if high_open_pct > settings.HIGH_OPEN_THRESHOLD and \
            drop_from_open < settings.HIGH_OPEN_DROP_THRESHOLD:
        return (True, SellStrategyType.HIGH_OPEN_DUMP.value, 90,
                SellAction.CLEAR_ALL.value,
                f"高开{high_open_pct:.2f}%后下跌{drop_from_open:.2f}%，非上升趋势，高开砸盘信号触发")
    return (False, "", 0, "", "")


def _check_danger_signal(pos: dict, indicators: dict) -> tuple:
    """Priority 85：危险信号（死叉/量价背离/ADX 减弱）。"""
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
        if len(signals) >= 2:
            action = SellAction.CLEAR_ALL.value
            detail = f"多重危险信号：{' + '.join(signals)}，建议清仓"
        else:
            action = SellAction.REDUCE_50.value
            detail = f"危险信号：{signals[0]}，建议减仓50%"
        return (True, SellStrategyType.DANGER_SIGNAL.value, 85, action, detail)
    return (False, "", 0, "", "")


def _check_trend_analysis(pos: dict, indicators: dict) -> tuple:
    """Priority 80：趋势分析（趋势股跌破 MA20 且 3 日未收回才清仓）。"""
    is_trend = bool(pos.get("is_trend_stock", False))
    if not is_trend:
        return (False, "", 0, "", "")
    trend_break = indicators.get("trend_break", False)
    if trend_break:
        return (True, SellStrategyType.TREND_ANALYSIS.value, 80,
                SellAction.CLEAR_ALL.value,
                "趋势股跌破20日均线且3日未收回，趋势反转确认，建议清仓")
    return (False, "", 0, "", "")


def _check_take_profit_stop_loss(pos: dict, pnl_pct: float, hold_days: int) -> tuple:
    """Priority 75：阶梯止盈 / 动态止损（阈值与实盘完全一致）。"""
    # 阶梯止盈
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
    # 动态止损
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


def _check_peak_reversal(pos: dict, bar: dict) -> tuple:
    """Priority 70：冲高回落（日级近似：peak_gain≈当日最高涨幅，retreat=峰值→收盘）。"""
    peak_gain = bar["peak_gain"]
    if peak_gain < settings.PEAK_REVERSAL_RISE:
        return (False, "", 0, "", "")
    retreat = peak_gain - bar["today_change"]
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


def _check_mandatory_reduction(pos: dict, bar: dict) -> tuple:
    """Priority 65：强制减仓（日级近似：涨幅达标且当日收 close<high 即「冲高未守新高」）。"""
    today_change = bar["today_change"]
    if today_change < settings.MANDATORY_RISE:
        return (False, "", 0, "", "")
    # 日级近似「未创新高」：当日冲高（high>open）但收盘未守住（close<high）
    high = bar["high"]
    close = bar["close"]
    open_ = bar["open"]
    if not (high > open_ and close < high):
        return (False, "", 0, "", "")
    return (True, SellStrategyType.MANDATORY_REDUCTION.value, 65,
            SellAction.REDUCE_50.value,
            f"涨幅{today_change:.2f}%≥{settings.MANDATORY_RISE}%且冲高未守新高，建议卖出50%")
