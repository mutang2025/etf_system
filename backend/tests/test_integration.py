"""集成测试：用临时库 + mock 数据源跑通买/卖扫描全链路并断言正确落库。"""

from src.trading.scan_tasks import run_buy_scan


def test_sell_signal_written_and_deduped(db, pos_manager, mock_provider):
    """持仓触发卖出 -> 信号落库；守护进程再次扫描 -> 同策略去重不再重复写入。"""
    code = mock_provider.get_etf_pool()[0].code
    rt = mock_provider.get_realtime_quote(code)
    buy_price = rt["price"] / 0.90  # 制造约 -10% 浮亏 -> 紧急熔断触发

    pos_manager.confirm_buy("SIG-X", code, "测试持仓", buy_price, buy_price * 1000)

    sigs1 = pos_manager.check_holdings_for_sell()
    assert any(s["sell_strategy"] == "紧急熔断" for s in sigs1)

    pending = db.get_signals(signal_type="sell", status="pending")
    assert len(pending) >= 1

    # 二次扫描：今日同持仓同策略已有待处理信号 -> 去重，不再新增紧急熔断
    sigs2 = pos_manager.check_holdings_for_sell()
    assert not any(s["sell_strategy"] == "紧急熔断" for s in sigs2)


def test_buy_scan_writes_signals(db, screening, buy_engine, pos_manager,
                                 mock_provider, monkeypatch):
    """买入扫描走完整链路，触发信号正确写入 signals 表。"""
    monkeypatch.setattr(mock_provider, "get_hs300_today_change", lambda: 0.0)

    result = run_buy_scan(screening, buy_engine, pos_manager, db)
    assert set(["scanned", "triggered", "signals"]).issubset(result.keys())

    pending = db.get_signals(signal_type="buy", status="pending")
    assert len(pending) >= result["triggered"]
