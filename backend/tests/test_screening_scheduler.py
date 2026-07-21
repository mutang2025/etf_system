"""四层选股自动调度器 —— 收盘后自动选股的 pytest 覆盖。

重点验证 _should_run_now 闸门（周末/收盘前/今日已跑/收盘后首次），
以及单例与 do_screening 调用链路（monkeypatch run_screening 避免真实选股耗时）。
"""

import asyncio
from datetime import datetime

import pytest

from src.screening_scheduler import ScreeningScheduler, get_screening_scheduler
from src.infrastructure.timeutil import CST


def _fake_now(cls, y, m, d, hh, mm):
    """构造一个 datetime 子类，now() 返回指定时刻（带 CST 时区）。"""

    class FakeNow(datetime):
        @classmethod
        def now(cls_, tz=None):
            return datetime(y, m, d, hh, mm, tzinfo=tz)

    return FakeNow


def test_gate_weekend(monkeypatch):
    """周六不应触发（即使已过收盘时刻）。2026-07-18 是周六。"""
    s = ScreeningScheduler()
    monkeypatch.setattr(
        "src.screening_scheduler.datetime", _fake_now(datetime, 2026, 7, 18, 16, 0)
    )
    assert s._should_run_now() is False


def test_gate_before_close(monkeypatch):
    """工作日但早于收盘后触发时刻（14:00 < 15:30）不应触发。"""
    s = ScreeningScheduler()
    monkeypatch.setattr(
        "src.screening_scheduler.datetime", _fake_now(datetime, 2026, 7, 20, 14, 0)
    )
    assert s._should_run_now() is False


def test_gate_after_close_first_run(monkeypatch):
    """工作日收盘后且今日尚未跑过 -> 触发。"""
    s = ScreeningScheduler()
    s._last_run_date = None
    monkeypatch.setattr(
        "src.screening_scheduler.datetime", _fake_now(datetime, 2026, 7, 20, 16, 0)
    )
    assert s._should_run_now() is True


def test_gate_already_ran_today(monkeypatch):
    """同一自然日已自动跑过 -> 不重复触发。"""
    s = ScreeningScheduler()
    s._last_run_date = "2026-07-20"
    monkeypatch.setattr(
        "src.screening_scheduler.datetime", _fake_now(datetime, 2026, 7, 20, 16, 0)
    )
    assert s._should_run_now() is False


def test_singleton():
    """get_screening_scheduler() 返回同一实例。"""
    a = get_screening_scheduler()
    b = get_screening_scheduler()
    assert a is b


def test_do_screening_runs_and_records(monkeypatch):
    """_do_screening 调用 run_screening 并记账（run_count / _last_run_date）。"""
    import src.presentation.routes as routes_mod

    s = ScreeningScheduler()

    async def fake_run():
        return {
            "summary": {"select_date": "2026-07-20"},
            "recommendations": [{"etf_code": "510300.SH"}],
            "pool_added": 1,
            "pool_skipped": 0,
            "is_empty_signal": False,
        }

    monkeypatch.setattr(routes_mod, "run_screening", fake_run)

    asyncio.run(s._do_screening())

    assert s.run_count == 1
    assert s._last_run_date is not None
    assert (s.last_run or {}).get("recommendations") == 1
    assert (s.last_run or {}).get("pool_added") == 1
