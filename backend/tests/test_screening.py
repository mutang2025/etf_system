"""选股引擎测试：P6 当日推荐缓存（避免守护进程每轮重跑四层漏斗）。"""

from datetime import datetime as _dt
from unittest import mock

import pytest

from src.screening import screening_engine as screening_mod
from conftest import FakeDateTime


def test_today_recommendations_cached(screening):
    """同一交易日第二次调用应直接返回缓存列表（不重跑全量筛选）。"""
    r1 = screening.get_today_recommendations()
    r2 = screening.get_today_recommendations()
    assert r1 is r2


def test_invalidate_cache_force_recompute(screening):
    r1 = screening.get_today_recommendations()
    screening.invalidate_cache()
    r2 = screening.get_today_recommendations()
    assert r1 is not r2


def test_cache_invalidated_next_day(screening):
    """跨交易日应重新计算（守护进程据此在开盘重置当日推荐）。"""
    r1 = screening.get_today_recommendations()
    with mock.patch.object(screening_mod, "datetime", FakeDateTime):
        FakeDateTime._now = _dt(2020, 1, 1, 12, 0)
        r2 = screening.get_today_recommendations()
    assert r1 is not r2
