"""卖出策略测试：P0-2 日内状态跨调用累积 / P2 组合级紧急熔断 / P3 空头排列触发危险信号。"""

from src.trading.sell_strategies import SellStrategyEngine
from conftest import make_klines


def _neutral_rt(code, change_pct, price):
    """构造"高开砸盘"不触发的实时行情（open==prev_close），便于隔离其它策略。"""
    return dict(code=code, change_pct=change_pct, open=price, prev_close=price,
                price=price, high=price * 1.02, low=price * 0.98,
                volume=1000, volume_ratio=1.0, amount=100.0)


def _position(code, buy_price, current_price, **kw):
    base = dict(etf_code=code, etf_name="测试", buy_price=buy_price,
                buy_shares=1000, buy_date="2026-01-01", hold_days=10,
                is_trend_stock=False, current_price=current_price)
    base.update(kw)
    return base


# ---------------- P0-2: 冲高回落/强制减仓 的日内状态累积 ----------------
def test_peak_reversal_accumulates_across_calls(scripted):
    """修复核心：共享卖出引擎下，日内峰值跨扫描调用累积，冲高回落后触发。"""
    code = "TEST.SH"
    scripted.set_klines(code, [])  # 无 K 线 -> 危险信号/趋势策略均不触发
    engine = SellStrategyEngine(scripted)

    pos = _position(code, buy_price=1.0, current_price=1.03)
    # 第一次：日内冲高 +3%，尚未回落 -> 不触发
    scripted.set_realtime(**_neutral_rt(code, change_pct=3.0, price=1.03))
    assert engine.check_all_strategies(pos) is None

    # 第二次：回落到 +1%（回落 2.0% >= 1.5% 档）-> 冲高回落触发
    scripted.set_realtime(**_neutral_rt(code, change_pct=1.0, price=1.01))
    sig = engine.check_all_strategies(pos)
    assert sig is not None
    assert sig.strategy_type == "冲高回落"


def test_fresh_engine_does_not_accumulate(scripted):
    """对照：每次重建引擎会让峰值清空 -> 这正是修复前的 bug（不应触发）。"""
    code = "T2.SH"
    scripted.set_klines(code, [])
    pos = _position(code, buy_price=1.0, current_price=1.03)

    e1 = SellStrategyEngine(scripted)
    scripted.set_realtime(**_neutral_rt(code, change_pct=3.0, price=1.03))
    e1.check_all_strategies(pos)  # 峰值 3.0 记在 e1，随后丢弃

    e2 = SellStrategyEngine(scripted)  # 全新引擎，峰值清零
    scripted.set_realtime(**_neutral_rt(code, change_pct=1.0, price=1.01))
    assert e2.check_all_strategies(pos) is None


# ---------------- P2: 紧急熔断以组合层面浮亏为准 ----------------
def test_emergency_circuit_portfolio_level(sell_engine):
    pos = _position("X.SH", buy_price=1.0, current_price=1.0)
    # 组合整体浮亏 -6% -> 触发（PRD 要求组合层面）
    trig, stype, prio, action, _ = sell_engine._check_emergency_circuit(
        pos, pnl_pct=0.0, pnl_amount=0.0, portfolio_pnl_pct=-6.0)
    assert trig is True and stype == "紧急熔断" and prio == 100

    # 组合 +1% 且单笔 +2% -> 不触发
    trig2, *_ = sell_engine._check_emergency_circuit(
        pos, pnl_pct=2.0, pnl_amount=20.0, portfolio_pnl_pct=1.0)
    assert trig2 is False

    # 组合 +1% 但单笔硬止损 -8% -> 仍触发（单笔额外安全网）
    trig3, *_ = sell_engine._check_emergency_circuit(
        pos, pnl_pct=-8.0, pnl_amount=-80.0, portfolio_pnl_pct=1.0)
    assert trig3 is True


# ---------------- P3: 空头排列触发危险信号 ----------------
def test_bearish_arrangement_triggers_danger_signal(scripted):
    """空头排列（修复后的"五重死叉"语义）应作为风控首关触发危险信号。"""
    code = "BEAR.SH"
    kl = make_klines(n=70, code=code, daily_return=-0.012, start=2.0)
    scripted.set_klines(code, kl)
    last = kl[-1].close
    scripted.set_realtime(**_neutral_rt(code, change_pct=0.0, price=last))

    engine = SellStrategyEngine(scripted)
    # buy_price==current_price -> 浮亏 0%，不会抢在危险信号前触发紧急熔断
    pos = _position(code, buy_price=last, current_price=last, hold_days=5)
    sig = engine.check_all_strategies(pos)
    assert sig is not None
    assert sig.strategy_type == "危险信号"
