"""买入信号测试：P5 主力资金异动改为确定性量比，不再随机。"""

from src.trading.buy_signal import BuySignalEngine
from conftest import make_klines


def _flat_klines(code="BUYTEST.SH", base_vol=1_000_000.0):
    """价格恒定 -> MA5 == 当前价；成交量恒定 -> 量比可控。"""
    return make_klines(n=70, code=code, start=1.0, daily_return=0.0, base_vol=base_vol)


def test_buy_triggers_when_volume_ratio_high(scripted):
    """量比=3.0（>=阈值2.0）且当日量放大 -> 三条件全满足。"""
    code = "BUYTEST.SH"
    scripted.set_klines(code, _flat_klines(code))
    scripted.set_realtime(code, change_pct=0.0, open=1.0, prev_close=1.0,
                          price=1.0, high=1.01, low=0.99,
                          volume=2_000_000.0, volume_ratio=3.0)
    engine = BuySignalEngine(scripted)
    triggered, details = engine.check_buy_conditions(code)
    assert triggered
    assert details["condition2"]["passed"]
    assert details["condition3"]["passed"]
    assert details["condition1"]["passed"]


def test_buy_does_not_trigger_when_volume_ratio_low(scripted):
    """量比=1.0（<阈值2.0）-> 条件2 不成立 -> 不触发（修复前是随机因子）。"""
    code = "BUYTEST.SH"
    scripted.set_klines(code, _flat_klines(code))
    scripted.set_realtime(code, change_pct=0.0, open=1.0, prev_close=1.0,
                          price=1.0, high=1.01, low=0.99,
                          volume=2_000_000.0, volume_ratio=1.0)
    from src.trading.buy_signal import BuySignalEngine
    engine = BuySignalEngine(scripted)
    triggered, details = engine.check_buy_conditions(code)
    assert not triggered
    assert details["condition2"]["passed"] is False


def test_buy_condition_is_deterministic(scripted):
    """同一输入两次调用结果一致（修复前 rng.uniform 导致不确定）。"""
    code = "BUYTEST.SH"
    scripted.set_klines(code, _flat_klines(code))
    scripted.set_realtime(code, change_pct=0.0, open=1.0, prev_close=1.0,
                          price=1.0, high=1.01, low=0.99,
                          volume=2_000_000.0, volume_ratio=3.0)
    from src.trading.buy_signal import BuySignalEngine
    engine = BuySignalEngine(scripted)
    _, d1 = engine.check_buy_conditions(code)
    _, d2 = engine.check_buy_conditions(code)
    # 条件2 说明应基于真实量比，而非"模拟/随机"
    assert d1["condition2"]["detail"] == d2["condition2"]["detail"]
    assert "随机" not in d1["condition2"]["detail"]
    assert "模拟" not in d1["condition2"]["detail"]
