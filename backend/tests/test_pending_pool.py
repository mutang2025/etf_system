"""待买入池 & 绩效看板·池历史 —— 今天新增功能的 pytest 覆盖。

设计：
- 全程 mock 数据源（conftest 在导入期锁定 DATA_SOURCE=mock），不触碰真实网络。
- 每个测试使用独立临时 SQLite 库（conftest 的 `db` 固件），不污染生产 etf.db。
- 覆盖：池子 DB 层增删改查 / 黑名单去重、买入扫描自动入池、卖出扫描覆盖池子并标记卖出、
  已卖出项不再纳入扫描、以及对应的 REST 路由（GET 列表 / POST 买入移出 / POST 人工移出 /
  GET 绩效含 pool_history）。
"""

import asyncio
import pytest

from src.trading.scan_tasks import run_buy_scan, run_sell_scan
from src.trading.position_manager import PositionManager
from src.presentation import routes as routes_mod


# ============================ 池子 DB 层 ============================
def test_add_to_pool_and_get(db):
    """新增 watching 项；同一 code 二次 add 被拒绝（去重 + 已卖出黑名单）。"""
    assert db.add_to_pool("P1.SH", "测试一", 1.23, "2026-07-16 09:30:00") is True
    row = db.get_pool_row("P1.SH")
    assert row is not None
    assert row["status"] == "watching"
    assert row["entry_price"] == 1.23
    # 二次 add 应被拒绝，且原 entry_price 不被覆盖
    assert db.add_to_pool("P1.SH", "测试一", 2.0, "2026-07-16 10:00:00") is False
    assert db.get_pool_row("P1.SH")["entry_price"] == 1.23


def test_mark_pool_sold_and_sold_codes(db):
    """标记卖出：状态置 sold、记录卖出点位与盈亏、进入黑名单集合。"""
    db.add_to_pool("P2.SH", "测试二", 10.0, "2026-07-16 09:30:00")
    assert db.mark_pool_sold("P2.SH", 9.0, "2026-07-16 15:00:00", -10.0) is True
    row = db.get_pool_row("P2.SH")
    assert row["status"] == "sold"
    assert row["sell_price"] == 9.0
    assert row["pnl_pct"] == -10.0
    assert "P2.SH" in db.get_pool_sold_codes()
    # watching 查询不应再包含已卖出项
    assert all(r["etf_code"] != "P2.SH" for r in db.get_pending_pool("watching"))


def test_remove_from_pool(db):
    """人工移出：watching 与 sold 项均可删除。"""
    db.add_to_pool("P3.SH", "测试三", 5.0, "2026-07-16 09:30:00")
    assert db.remove_from_pool("P3.SH") is True
    assert db.get_pool_row("P3.SH") is None
    # 已卖出项也可人工移出
    db.add_to_pool("P4.SH", "测试四", 5.0, "2026-07-16 09:30:00")
    db.mark_pool_sold("P4.SH", 4.0, "2026-07-16 15:00:00", -20.0)
    assert db.remove_from_pool("P4.SH") is True
    assert db.get_pool_row("P4.SH") is None


# ============================ scan_tasks 全链路 ============================
def test_buy_scan_auto_adds_to_pool(db, screening, buy_engine, pos_manager,
                                     mock_provider, monkeypatch):
    """买入扫描：每个被触发的信号自动入池（入池点位=信号现价>0）。"""
    monkeypatch.setattr(mock_provider, "get_hs300_today_change", lambda: 0.0)
    before = len(db.get_pending_pool("watching"))
    result = run_buy_scan(screening, buy_engine, pos_manager, db)
    after = len(db.get_pending_pool("watching"))
    assert after - before >= result["triggered"]
    assert all(r["entry_price"] > 0 for r in db.get_pending_pool("watching"))


def test_buy_scan_does_not_duplicate_pool(db, screening, buy_engine, pos_manager,
                                          mock_provider, monkeypatch):
    """二次买入扫描：已入池项不再重复加入（add_to_pool 拒绝 -> 池子不增长）。"""
    monkeypatch.setattr(mock_provider, "get_hs300_today_change", lambda: 0.0)
    run_buy_scan(screening, buy_engine, pos_manager, db)
    first = len(db.get_pending_pool("watching"))
    run_buy_scan(screening, buy_engine, pos_manager, db)
    assert len(db.get_pending_pool("watching")) == first


def test_sell_scan_covers_pool_and_marks_sold(db, scripted):
    """卖出扫描覆盖池子：以入池点位为成本命中卖出信号 -> 标记 sold、记点位与盈亏。"""
    code = "POOLSELL.SH"
    scripted.set_realtime(code, price=8.0, prev_close=10.0,
                          change_pct=-20.0, open=10.0, high=10.0, low=8.0,
                          volume=1_000_000.0)
    db.add_to_pool(code, "池卖出测试", entry_price=10.0,
                  enter_time="2026-07-16 09:30:00")
    pm = PositionManager(db, scripted)
    result = run_sell_scan(pm)
    sold = db.get_pool_row(code)
    assert sold["status"] == "sold"
    assert sold["sell_price"] == 8.0
    assert sold["pnl_pct"] == -20.0
    assert any(p["etf_code"] == code for p in result["pool_sold"])


def test_sold_pool_not_rescanned_by_sell(db, scripted):
    """已卖出项不再纳入卖出扫描（扫描只覆盖 watching）。"""
    code = "SOLDRES.SH"
    scripted.set_realtime(code, price=8.0, prev_close=10.0,
                          change_pct=-20.0, open=10.0, high=10.0, low=8.0,
                          volume=1_000_000.0)
    db.add_to_pool(code, "已卖不扫", entry_price=10.0,
                  enter_time="2026-07-16 09:30:00")
    db.mark_pool_sold(code, 8.0, "2026-07-16 15:00:00", -20.0)
    pm = PositionManager(db, scripted)
    result = run_sell_scan(pm)
    assert all(p["etf_code"] != code for p in result["pool_sold"])


# ============================ REST 路由 ============================
@pytest.fixture
def route_env(db):
    """重置 routes 模块级单例，使其指向当前测试的临时库。"""
    routes_mod._db = None
    routes_mod._pos_manager = None
    routes_mod._screening = None
    routes_mod._buy_engine = None
    yield
    routes_mod._db = None
    routes_mod._pos_manager = None
    routes_mod._screening = None
    routes_mod._buy_engine = None


def test_pending_pool_route_crud(db, route_env, mock_provider):
    """GET 列表 / 富集实时价 / POST 买入建仓并移出 / POST 移出不存在项 404。"""
    code = mock_provider.get_etf_pool()[0].code
    r = asyncio.run(routes_mod.get_pending_pool(None))
    assert r["total"] == 0

    db.add_to_pool(code, "路由测试", 2.0, "2026-07-16 09:30:00")
    r = asyncio.run(routes_mod.get_pending_pool(None))
    assert r["total"] == 1
    item = r["data"][0]
    assert item["etf_code"] == code
    assert item["current_price"] is not None  # 路由层富集实时价

    before = len(db.get_positions(status="holding"))
    r = asyncio.run(routes_mod.buy_from_pool(code, None))
    assert r["etf_code"] == code
    assert db.get_pool_row(code) is None  # 买入后自动移出
    assert len(db.get_positions(status="holding")) == before + 1

    with pytest.raises(Exception):
        asyncio.run(routes_mod.remove_from_pool("DOESNOTEXIST.SH"))


def test_performance_pool_history(db, route_env):
    """绩效接口应包含待买入池已卖出历史（pool_history）。"""
    db.add_to_pool("HIST.SH", "历史测试", 1.0, "2026-07-10 09:30:00")
    db.mark_pool_sold("HIST.SH", 1.1, "2026-07-15 14:00:00", 10.0)
    data = asyncio.run(routes_mod.get_performance())
    assert "pool_history" in data
    codes = [h["etf_code"] for h in data["pool_history"]]
    assert "HIST.SH" in codes
    rec = next(h for h in data["pool_history"] if h["etf_code"] == "HIST.SH")
    assert rec["sell_price"] == 1.1
    assert rec["pnl_pct"] == 10.0
    assert rec["status"] == "sold"
