"""P1 修复回归测试。

覆盖：
- P1-1 买入金额：建议金额受单只上限 + 总仓位上限约束，并扣除已持仓；
        确认买入超出可用资金（触达总仓位上限）被拒绝。
- P1-2 建仓事务 + 防重复开仓：同一 ETF 不可重复开仓；平仓后可再次开仓；
        持仓唯一索引生效。
- P1-3 收紧 CORS + 可选 Bearer 鉴权：API_TOKEN 为空时开放；
        设置后缺 Token 返回 401，带正确 Token 放行；路由已挂鉴权依赖。
- P1-4 akshare 数据失败告警：_alert 记录并触发回调，健康检查暴露 data_alert。
"""

import asyncio
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from config import settings
from src.presentation.security import require_auth
from src.presentation.routes import router
from src.infrastructure.akshare_data_provider import (
    AKShareDataProvider,
    set_data_alert_callback,
)


# ============================ P1-1 买入金额 ============================
def test_suggested_buy_amount_empty_portfolio(pos_manager):
    """空仓时建议金额 = 总资金 × 单只上限（30% = 30000）。"""
    assert pos_manager.suggested_buy_amount() == 30000.0
    assert pos_manager.get_available_capital() == 100000.0


def test_suggested_buy_amount_respects_total_cap(db, pos_manager):
    """已投入 90000（>80% 上限）时，建议金额应为 0（不可再开仓）。"""
    db.save_position({
        "etf_code": "CAP.SH", "etf_name": "占仓测试",
        "buy_date": "2026-07-17", "buy_price": 1.0,
        "buy_amount": 90000.0, "buy_shares": 90000.0,
        "current_price": 1.0, "current_value": 90000.0,
    })
    # 可用资金 = 100000 - 90000 = 10000
    assert pos_manager.get_available_capital() == 10000.0
    # 总仓位余量 = 80000 - 90000 = -10000 -> 建议金额被夹到 0
    assert pos_manager.suggested_buy_amount() == 0.0


def test_confirm_buy_rejects_over_cap(pos_manager, mock_provider):
    """买入金额超过总仓位上限（80%）时被拒绝。"""
    code = mock_provider.get_etf_pool()[0].code
    with pytest.raises(ValueError, match="超出可用资金"):
        pos_manager.confirm_buy(
            signal_id="S-OVER", etf_code=code, etf_name="x",
            buy_price=1.0, buy_amount=90000.0,  # 90000 > 80000 上限余量
        )


def test_buy_signal_cap_aware_amount(pos_manager, buy_engine, mock_provider):
    """generate_buy_signal 在传入可用资金=0 时建议金额为 0。"""
    code = mock_provider.get_etf_pool()[0].code
    sig = buy_engine.generate_buy_signal(code, "x", {}, available_capital=0.0)
    if sig is not None:  # 该标的可能未触发三条件，不强制
        assert sig.suggested_amount == 0.0


# ====================== P1-2 事务 / 防重复开仓 ======================
def test_confirm_buy_duplicate_blocked(pos_manager, mock_provider):
    """同一 ETF 不可重复开仓；重复时抛错且信号状态不被污染。"""
    code = mock_provider.get_etf_pool()[0].code

    # 第一次建仓成功
    pos = pos_manager.confirm_buy(
        signal_id="S1", etf_code=code, etf_name="x",
        buy_price=1.0, buy_amount=10000.0,
    )
    assert pos["id"] is not None
    assert pos_manager.db.has_open_position(code) is True
    assert pos_manager.db.get_positions(status="holding")[0]["buy_amount"] == 10000.0

    # 第二次同一 ETF 建仓 -> 拒绝
    with pytest.raises(ValueError, match="已在持仓中"):
        pos_manager.confirm_buy(
            signal_id="S2", etf_code=code, etf_name="x",
            buy_price=1.0, buy_amount=5000.0,
        )
    # 持仓仍只有一笔，未被部分写入
    assert len(pos_manager.db.get_positions(status="holding")) == 1


def test_close_then_reopen_allowed(pos_manager, mock_provider):
    """平仓后（status=sold）唯一索引释放，可再次开仓同一 ETF。"""
    code = mock_provider.get_etf_pool()[1].code

    pos = pos_manager.confirm_buy(
        signal_id="S-A", etf_code=code, etf_name="x",
        buy_price=1.0, buy_amount=10000.0,
    )
    assert pos_manager.db.has_open_position(code) is True

    # 平仓（事务）：返回的是更新前快照，故以 DB 状态为准
    pos_manager.close_position(pos["id"], sell_price=1.1)
    assert pos_manager.db.has_open_position(code) is False
    closed = pos_manager.db.get_closed_positions()
    assert len(closed) == 1
    assert closed[0]["status"] == "sold"

    # 再次开仓同一 ETF —— 部分唯一索引仅约束 holding，应成功
    pos2 = pos_manager.confirm_buy(
        signal_id="S-B", etf_code=code, etf_name="x",
        buy_price=1.0, buy_amount=5000.0,
    )
    assert pos2["id"] is not None
    assert pos_manager.db.has_open_position(code) is True


def test_confirm_buy_zero_amount_rejected(pos_manager, mock_provider):
    """买入金额必须 > 0。"""
    code = mock_provider.get_etf_pool()[2].code
    with pytest.raises(ValueError) as exc:
        pos_manager.confirm_buy(
            signal_id="S0", etf_code=code, etf_name="x",
            buy_price=1.0, buy_amount=0.0,
        )
    assert "买入金额" in str(exc.value)


# ====================== P1-3 CORS / 鉴权 ======================
def test_security_config_fields_exist():
    assert hasattr(settings, "API_TOKEN")
    assert hasattr(settings, "CORS_ALLOWED_ORIGINS")


def test_router_has_auth_dependency():
    assert any(
        getattr(d.dependency, "__name__", "") == "require_auth"
        for d in router.dependencies
    )


def test_auth_open_when_no_token():
    """API_TOKEN 为空：开放模式，不鉴权。"""
    settings.API_TOKEN = ""
    assert asyncio.run(require_auth(creds=None)) is None


def test_auth_requires_token_when_set():
    """API_TOKEN 设置后：缺 Token 返回 401。"""
    settings.API_TOKEN = "secret123"
    try:
        asyncio.run(require_auth(creds=None))
        assert False, "should raise 401"
    except HTTPException as e:
        assert e.status_code == 401


def test_auth_passes_with_valid_token():
    """API_TOKEN 设置后：携带正确 Token 放行。"""
    settings.API_TOKEN = "secret123"
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="secret123")
    # 不抛异常即通过
    assert asyncio.run(require_auth(creds=creds)) is None
    settings.API_TOKEN = ""  # 还原，避免影响其它用例


# ====================== P1-4 数据失败告警 ======================
def test_akshare_alert_hook_and_health():
    """_alert 记录最近告警 + 触发回调；健康检查暴露 data_alert 字段。"""
    captured = []
    set_data_alert_callback(lambda m: captured.append(m))

    # 绕过 __init__ 的真实网络初始化，仅构造最小实例验证告警逻辑
    p = AKShareDataProvider.__new__(AKShareDataProvider)
    p._last_alert = None
    p._realtime_cache = {}
    p._etf_pool = []
    p._kline_cache = {}
    p._last_realtime_update = 0
    p._hs300_klines = []

    class _Store:
        def stats(self):
            return {"cached_symbols": 0}

    p._kline_store = _Store()

    p._alert("数据源异常：spot_em 失败")
    assert p._last_alert == "数据源异常：spot_em 失败"
    assert captured == ["数据源异常：spot_em 失败"]

    health = p.get_health_status()
    assert "data_alert" in health
    assert health["data_alert"] == "数据源异常：spot_em 失败"

    set_data_alert_callback(None)
