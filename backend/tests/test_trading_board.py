"""交易看板（多指数）& ETF 池定时同步 —— 今天新增功能的 pytest 覆盖。

设计：
- 全部 mock 数据源（conftest 锁定），无网络依赖。
- 交易看板：7 大指数 + 市场宽度结构、K 线对有效/无效代码的边界、确定性（同代码两次一致）。
- 定时同步：_should_sync_now 闸门（周末/收盘前/今日已同步/收盘后首次）、
  _do_sync 记账（sync_count 与 _last_synced_date）、单例。
"""

import asyncio
import datetime as _rdt
import pytest

from src.infrastructure.market_indices import get_index_provider
from src.pool_sync_scheduler import PoolSyncScheduler, CST, get_pool_sync_scheduler


# ============================ 交易看板 · 指数源 ============================
def test_index_quotes_shape():
    """报价结构：data_source 合法、8 大指数齐全、市场宽度字段完整。"""
    prov = get_index_provider()
    q = prov.get_index_quotes()
    assert q["data_source"] in ("mock", "akshare")
    assert len(q["indices"]) == 8
    names = {i["name"] for i in q["indices"]}
    for expected in ("沪深300", "创业板指", "上证指数", "北证50", "科创50", "深证成指", "上证50", "恒生指数"):
        assert expected in names
    assert set(q["breadth"].keys()) >= {"up", "down", "flat", "limit_up", "limit_down"}


def test_index_klines_valid_and_invalid():
    """K 线：有效代码返回数据且确定性一致；无效代码返回空列表。"""
    prov = get_index_provider()
    r = prov.get_index_klines("000300.SH", 60)
    assert r["code"] == "000300.SH"
    assert len(r["klines"]) > 0
    # 确定性：以代码为随机种子，两次结果一致（图表不会乱跳）
    r2 = prov.get_index_klines("000300.SH", 60)
    assert [k["close"] for k in r["klines"]] == [k["close"] for k in r2["klines"]]
    bad = prov.get_index_klines("ZZZ999", 60)
    assert bad["klines"] == []


# ============================ ETF 池定时同步 ============================
def test_scheduler_gate(db, monkeypatch):
    """_should_sync_now 闸门：收盘后首日触发；周末/收盘前/今日已同步均不触发。"""
    import src.pool_sync_scheduler as sched

    class _FakeDT:
        NOW = None

        @classmethod
        def now(cls, tz=None):
            return cls.NOW

        @classmethod
        def strptime(cls, *a, **k):
            return _rdt.datetime.strptime(*a, **k)

    monkeypatch.setattr(sched, "datetime", _FakeDT)
    s = PoolSyncScheduler()
    s._last_synced_date = None

    # 周二 16:00（已过 15:30 收盘后）-> 应触发
    _FakeDT.NOW = _rdt.datetime(2026, 7, 15, 16, 0, tzinfo=CST)
    assert s._should_sync_now() is True

    # 今日已同步 -> 不再触发（保证每日最多一次）
    s._last_synced_date = _FakeDT.NOW.strftime("%Y-%m-%d")
    assert s._should_sync_now() is False

    # 15:30 之前 -> 不触发
    s._last_synced_date = None
    _FakeDT.NOW = _rdt.datetime(2026, 7, 15, 14, 0, tzinfo=CST)
    assert s._should_sync_now() is False

    # 周六 -> 不触发（工作日近似，weekday<5）
    _FakeDT.NOW = _rdt.datetime(2026, 7, 19, 16, 0, tzinfo=CST)
    assert s._should_sync_now() is False


def test_scheduler_do_sync_records_date(db, monkeypatch):
    """_do_sync：sync_count 自增、_last_synced_date 记录今日、result 含同步统计。"""
    import src.pool_sync_scheduler as sched
    monkeypatch.setattr(sched, "datetime", _rdt.datetime)  # 用真实 datetime
    s = PoolSyncScheduler()
    asyncio.run(s._do_sync())
    assert s.sync_count == 1
    today = _rdt.datetime.now(CST).strftime("%Y-%m-%d")
    assert s._last_synced_date == today
    assert s.last_sync is not None
    assert s.last_sync["result"]["total"] > 0


def test_scheduler_singleton(tmp_path, monkeypatch):
    """模块级单例：两次获取为同一对象。"""
    from config import settings
    from database import init_db
    p = tmp_path / "sched.db"
    settings.DB_PATH = str(p)
    init_db(str(p))
    monkeypatch.setattr("src.pool_sync_scheduler._scheduler", None)
    a = get_pool_sync_scheduler()
    b = get_pool_sync_scheduler()
    assert a is b
