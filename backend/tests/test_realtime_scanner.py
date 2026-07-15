"""盘中自动扫描守护进程测试：P0-1（原缺失的"自动盯盘"循环）。

仅验证守护进程的核心契约：单例、启停标志、交易时段门控、扫描计数递增、
SSE 推送发布、状态结构。不依赖真实网络（全程 mock 数据源 + 临时库）。
"""

import asyncio
from datetime import datetime as _dt
from unittest import mock

import pytest

from config import settings
from database import init_db
from src.realtime_scanner import get_scanner
from src import realtime_scanner as scanner_mod
from src.infrastructure.mock_data_provider import get_mock_provider
from conftest import FakeDateTime


@pytest.fixture(autouse=True)
def _isolated_scanner(tmp_path):
    """每个测试用独立临时库 + 全新守护进程单例，避免污染生产库与单例串扰。"""
    settings.DB_PATH = str(tmp_path / "scanner.db")
    init_db(settings.DB_PATH)
    scanner_mod._scanner = None
    yield
    scanner_mod._scanner = None


def test_scanner_is_singleton():
    assert get_scanner() is get_scanner()


def test_start_stop_flags():
    scanner = get_scanner()
    assert scanner.is_running() is False
    scanner._running = True
    assert scanner.is_running() is True
    scanner.stop()
    assert scanner.is_running() is False


def test_trading_hours_gate():
    scanner = get_scanner()
    with mock.patch.object(scanner_mod, "datetime", FakeDateTime):
        # 周三 10:00 -> 交易时段内
        FakeDateTime._now = _dt(2026, 1, 7, 10, 0)
        assert scanner._in_trading_hours() is True
        # 周六 10:00 -> 非交易时段
        FakeDateTime._now = _dt(2026, 1, 10, 10, 0)
        assert scanner._in_trading_hours() is False


def test_do_scan_increments_and_publishes(monkeypatch):
    """_do_scan 应递增扫描计数并产出含 buy/sell 的结果（守护进程核心产出）。"""
    scanner = get_scanner()
    # 强制沪深300无空仓信号，使买入扫描走完整路径
    monkeypatch.setattr(get_mock_provider(), "get_hs300_today_change", lambda: 0.0)

    before = scanner.scan_count
    asyncio.run(scanner._do_scan())
    assert scanner.scan_count == before + 1

    last = scanner.last_scan
    assert last is not None
    assert set(["scan_count", "timestamp", "buy", "sell"]).issubset(last.keys())
    assert isinstance(last["buy"], dict) and isinstance(last["sell"], dict)
    assert "scanned" in last["buy"] and "triggered" in last["buy"]


def test_subscribe_publish_queue():
    """SSE 订阅队列能收到守护进程发布的结果帧。"""
    scanner = get_scanner()

    async def _run():
        q = scanner.subscribe()
        await scanner._publish({"hello": 1})
        item = await asyncio.wait_for(q.get(), timeout=2)
        scanner.unsubscribe(q)
        return item

    assert asyncio.run(_run()) == {"hello": 1}


def test_status_shape():
    scanner = get_scanner()
    status = scanner.get_status()
    assert set(["running", "scan_count", "started_at", "in_trading_hours",
                "scan_interval_seconds", "last_scan", "last_error"]).issubset(status.keys())
