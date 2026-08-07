"""自动交易（信号触发即自动成交）单元测试。

覆盖：
- 同策略冷却守卫（防守护进程 10s 循环重复减仓）
- 自动买入：开启时确认建仓、关闭时保留 pending
- 自动卖出：开启时清仓并标记信号 executed、关闭时不动作
全程使用 mock 数据源，无网络依赖。
"""
import pytest

from config import settings
from src.domain.entities import BuySignal
from src.trading.scan_tasks import (
    auto_confirm_buy,
    auto_execute_sell,
    _auto_sell_allowed,
    _record_auto_sell,
)


def _real_code(mock_provider):
    """取 mock 池中真实存在的代码，避免指标/行情缺失导致建仓失败。"""
    return mock_provider.get_etf_pool()[0].code


def test_auto_sell_cooldown_guard(monkeypatch):
    # 默认冷却 300s，记录后立刻应被拦截；冷却置 0 后放行
    monkeypatch.setattr(settings, "AUTO_SELL_COOLDOWN_SECONDS", 300)
    key = ("X.SH", "强制减仓")
    assert _auto_sell_allowed(key) is True
    _record_auto_sell(key)
    assert _auto_sell_allowed(key) is False
    monkeypatch.setattr(settings, "AUTO_SELL_COOLDOWN_SECONDS", 0)
    assert _auto_sell_allowed(key) is True


def test_auto_confirm_buy_off_leaves_pending(db, pos_manager, mock_provider, monkeypatch):
    monkeypatch.setattr(settings, "AUTO_EXECUTE_BUY", False)
    code = _real_code(mock_provider)
    sig = BuySignal("BUY-1", code, "测试", "2025-01-01 09:30:00", 1.0, 0.5, 30000.0, {}, {})
    ok = auto_confirm_buy(pos_manager, db, sig, "BUY-1")
    assert ok is False
    assert db.get_holding_positions() == []  # 未建仓，信号保留 pending


def test_auto_confirm_buy_on_creates_position(db, pos_manager, mock_provider, monkeypatch):
    monkeypatch.setattr(settings, "AUTO_EXECUTE_BUY", True)
    code = _real_code(mock_provider)
    sig = BuySignal("BUY-2", code, "测试", "2025-01-01 09:30:00", 1.0, 0.5, 30000.0, {}, {})
    ok = auto_confirm_buy(pos_manager, db, sig, "BUY-2")
    assert ok is True
    holdings = db.get_holding_positions()
    assert len(holdings) == 1
    assert holdings[0]["etf_code"] == code


def test_auto_execute_sell_on_closes_position(db, pos_manager, mock_provider, monkeypatch):
    monkeypatch.setattr(settings, "AUTO_EXECUTE_SELL", True)
    monkeypatch.setattr(settings, "AUTO_SELL_COOLDOWN_SECONDS", 300)
    code = _real_code(mock_provider)
    # 先建仓
    pos = pos_manager.confirm_buy(
        signal_id="BUY-3", etf_code=code, etf_name="测试", buy_price=1.0, buy_amount=30000.0,
    )
    pos_id = pos["id"]
    # 预置一条 pending 卖出信号（CLEAR_ALL），供 mark_sell_signal_executed 匹配
    db.save_signal({
        "signal_id": "SELL-1", "signal_type": "sell", "etf_code": code, "etf_name": "测试",
        "trigger_time": "2025-01-01 09:30:00", "price": 0.95, "sell_strategy": "紧急熔断",
        "sell_priority": 100, "sell_action": "CLEAR_ALL", "pnl_amount": -1500.0,
        "pnl_pct": -5.0, "status": "pending",
    })
    sell_sig = {
        "etf_code": code, "etf_name": "测试", "sell_strategy": "紧急熔断",
        "sell_priority": 100, "sell_action": "CLEAR_ALL", "pnl_amount": -1500.0,
        "pnl_pct": -5.0, "status": "pending", "signal_id": "SELL-1",
        "price": 0.95, "position_id": pos_id, "buy_price": 1.0, "hold_days": 3,
    }
    ok = auto_execute_sell(pos_manager, sell_sig)
    assert ok is True
    assert db.get_holding_positions() == []  # 已平仓
    # 卖出信号应被标记为 executed
    sigs = db.get_signals(signal_type="sell", status="executed")
    assert any(s["signal_id"] == "SELL-1" for s in sigs)


def test_auto_execute_sell_off_does_nothing(db, pos_manager, mock_provider, monkeypatch):
    monkeypatch.setattr(settings, "AUTO_EXECUTE_SELL", False)
    code = _real_code(mock_provider)
    pos = pos_manager.confirm_buy(
        signal_id="BUY-4", etf_code=code, etf_name="测试", buy_price=1.0, buy_amount=30000.0,
    )
    sell_sig = {
        "etf_code": code, "sell_strategy": "紧急熔断", "sell_action": "CLEAR_ALL",
        "price": 0.95, "position_id": pos["id"], "status": "pending",
    }
    ok = auto_execute_sell(pos_manager, sell_sig)
    assert ok is False
    assert len(db.get_holding_positions()) == 1  # 未平仓
