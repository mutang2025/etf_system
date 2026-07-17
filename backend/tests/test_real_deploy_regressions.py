"""真实部署（akshare 真实接口）跑出的 4 个 bug 的回归测试。

这些 bug 在 mock 模式下永远不会触发，只在接真实网络数据时才暴露。
把它们固化为单测，防止以后被“看起来无害”的改动悄悄改坏。

  Bug #1  SellAction 枚举 .value 被写成中文（"减仓50%"）
           -> parse_reduce_ratio('REDUCE_50') 查中文 key 命中 None
           -> 减仓动作永远走成全平（close），REDUCE 不执行
  Bug #2  mark_sell_signal_executed 按 sell_strategy(中文分类) 匹配
           -> 前端发的是英文 sell_action('REDUCE_50')
           -> 信号永远残留 pending，既没减仓也没消费
  Bug #3  buy_from_pool 路由缺 try/except
           -> 持仓中再买同 ETF 时 confirm_buy 抛 ValueError(防重)
           -> 异常裸奔成 500（正确应返回 409）
  Bug #4  真实行情里个别 ETF（如新股无昨收）涨跌幅为 inf/nan
           -> round(inf, 2) 仍是非有限浮点
           -> FastAPI 序列化 JSON 时抛 ValueError -> 整批 /api/realtime 500
"""

import json

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.domain.enums import SellAction, parse_reduce_ratio
from src.infrastructure.akshare_data_provider import AKShareDataProvider
from src.infrastructure.data_provider_factory import get_data_provider
from src.presentation import routes
from src.trading.position_manager import PositionManager


# --------------------------------------------------------------------------
# Bug #1 — SellAction 枚举值必须是英文契约名（根因锁死）
# --------------------------------------------------------------------------
def test_sell_action_enum_value_is_english_contract():
    """枚举的 .value 必须等于英文成员名，而非中文展示串。

    一旦有人把 .value 改回中文（如 "减仓50%"），这套断言立刻 FAIL，
    因为前端的英文 sell_action 与后端的字典 key 会重新错位。
    """
    assert SellAction.REDUCE_50.value == "REDUCE_50"
    assert SellAction.REDUCE_33.value == "REDUCE_33"
    assert SellAction.REDUCE_HALF.value == "REDUCE_HALF"
    assert SellAction.CLEAR_ALL.value == "CLEAR_ALL"


def test_parse_reduce_ratio_uses_english_action():
    """parse_reduce_ratio 必须按英文 sell_action 解析出减仓比例。"""
    assert parse_reduce_ratio("REDUCE_50") == 0.5
    assert abs(parse_reduce_ratio("REDUCE_33") - 1 / 3) < 1e-9
    assert parse_reduce_ratio("REDUCE_HALF") == 0.5
    assert parse_reduce_ratio("CLEAR_ALL") is None
    # 用 .value 调用也必须正确（复现 #1 的触发路径）
    assert parse_reduce_ratio(SellAction.REDUCE_50.value) == 0.5


# --------------------------------------------------------------------------
# Bug #2 — 减仓信号按 sell_action(英文) 匹配，而非 sell_strategy(中文)
# --------------------------------------------------------------------------
def test_reduce_marks_signal_by_sell_action_not_strategy(pos_manager):
    """减仓后必须消费'英文 sell_action'对应的待处理信号。

    真实链路：sell_strategies 落库的信号 sell_strategy 是中文分类（"强制减仓"），
    而 UI 发出的是英文 sell_action（"REDUCE_50"）。
    这里故意让调用时的 sell_strategy 也传英文（与信号中文策略不同），
    仅 sell_action 一致 —— 只有在"按 sell_action 匹配"时才应命中并置 executed。
    """
    pos = pos_manager.confirm_buy(
        signal_id="REG-2", etf_code="999006.SH", etf_name="减仓信号匹配",
        buy_price=2.0, buy_amount=2000.0,
    )
    pos_id = pos["id"]

    # 落库：sell_strategy 中文、sell_action 英文
    pos_manager.db.save_signal({
        "signal_id": "SELL-REG-2", "signal_type": "sell",
        "etf_code": "999006.SH", "sell_strategy": "强制减仓",
        "sell_action": "REDUCE_50", "status": "pending",
        "pnl_amount": 0, "pnl_pct": 0,
    })

    pos_manager.reduce_position(
        pos_id, sell_price=2.4, ratio=0.5,
        sell_strategy="REDUCE_50",   # 故意与信号的中文策略不同
        etf_code="999006.SH",
        sell_action="REDUCE_50", current_price=2.4,
    )

    row = pos_manager.db.conn.execute(
        "SELECT status FROM signals WHERE signal_id=?", ("SELL-REG-2",)
    ).fetchone()
    assert dict(row)["status"] == "executed"


# --------------------------------------------------------------------------
# Bug #3 — buy_from_pool 重复开仓必须返回 409，不能是 500
# --------------------------------------------------------------------------
@pytest.fixture
def buy_client(db, mock_provider):
    """用依赖覆盖搭一个只挂 routes.router 的极简 app，避开 main 的启动守护进程。"""
    app = FastAPI()
    app.include_router(routes.router)
    # 把路由里的全局依赖换成测试固件，避免触碰真实网络单例
    app.dependency_overrides[routes.get_db] = lambda: db
    app.dependency_overrides[routes.get_pos_manager] = \
        lambda: PositionManager(db, mock_provider)
    app.dependency_overrides[routes.get_data_provider] = lambda: mock_provider

    # 放一只 watching 池项（entry_price 是 NOT NULL 列，必须给）
    db.conn.execute(
        "INSERT INTO pending_buy_pool (etf_code, etf_name, entry_price, status) "
        "VALUES (?, ?, ?, 'watching')",
        ("999101.SH", "回归测试ETF", 1.5),
    )
    db.conn.commit()
    return TestClient(app)


def test_buy_from_pool_duplicate_returns_409(buy_client, db):
    code = "999101.SH"

    # 首次买入成功（建仓 + 移出池）
    r1 = buy_client.post(f"/api/pending-pool/{code}/buy", json={})
    assert r1.status_code == 200
    assert r1.json()["etf_code"] == code

    # buy_from_pool 成功后会 remove_from_pool，这里重新放回池以便复买
    db.conn.execute(
        "INSERT INTO pending_buy_pool (etf_code, etf_name, entry_price, status) "
        "VALUES (?, ?, ?, 'watching')",
        (code, "回归测试ETF", 1.5),
    )
    db.conn.commit()

    # 持仓中再买同 ETF -> 应 409（旧代码 confirm_buy 抛 ValueError 裸奔成 500）
    r2 = buy_client.post(f"/api/pending-pool/{code}/buy", json={})
    assert r2.status_code == 409
    assert "重复开仓" in r2.json()["detail"]


# --------------------------------------------------------------------------
# Bug #4 — 真实行情含 inf/nan 涨跌幅时，必须兜底为 None 且可 JSON 序列化
# --------------------------------------------------------------------------
def test_realtime_quote_inf_nan_does_not_crash():
    """构造一支正常 + 一支涨跌幅为 inf 的行情，验证 _load_realtime_quotes 不崩。

    旧代码：round(float('inf'), 2) 仍是 inf，写入缓存后 FastAPI 序列化
    /api/realtime 时抛 ValueError('Out of range float values are not JSON compliant') -> 500。
    修复后：非有限浮点统一兜底为 None；且整批行情可 json.dumps。
    """
    # 不触发 __init__ 的网络加载，直接构造裸实例并手工置缓存
    p = AKShareDataProvider.__new__(AKShareDataProvider)
    p._realtime_cache = {}

    bad_df = pd.DataFrame([
        {"代码": "510300", "名称": "沪深300ETF", "最新价": 4.0, "涨跌幅": 1.5,
         "成交量": 100000, "成交额": 400000, "开盘价": 4.0, "最高价": 4.1,
         "最低价": 3.9, "昨收": 3.94, "量比": 1.0},
        # 新股无昨收 -> 真实 akshare 会给出 inf 涨跌幅
        {"代码": "511880", "名称": "银华日利", "最新价": 100.0, "涨跌幅": float("inf"),
         "成交量": 100000, "成交额": 400000, "开盘价": 100.0, "最高价": 100.1,
         "最低价": 99.9, "昨收": 0.0, "量比": 1.0},
    ])
    p._fetch_spot_em = lambda: bad_df

    # 不应抛异常（复现旧代码的 inf -> JSON 500）
    p._load_realtime_quotes()

    # 正常项保持数值
    assert p._realtime_cache["510300.SH"]["change_pct"] == 1.5
    # 异常项兜底为 None（而非 inf）
    assert p._realtime_cache["511880.SH"]["change_pct"] is None

    # 整批行情可 JSON 序列化（这是旧代码 500 的直接根因）
    json.dumps(p.get_all_realtime_quotes())
