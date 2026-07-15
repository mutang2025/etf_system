"""白名单小池 + 落盘 K 线缓存 的单元测试。

覆盖：
- get_scan_universe：akshare 模式只返回白名单交集；mock 模式返回全池（不被白名单影响）。
- PersistentKlineStore：往返一致、新鲜度判定（跨交易日自动失效）、空输入安全。
"""

from datetime import datetime as _dt, timedelta

import pytest

from src.domain.entities import DailyKline, ETF
from src.infrastructure.kline_cache import PersistentKlineStore
from conftest import FakeDateTime


# --------------------------------------------------------------------------
# get_scan_universe
# --------------------------------------------------------------------------
def _fake_provider_with_pool(codes):
    """构造一个只实现 get_etf_pool 的假 provider。"""

    class _P:
        def __init__(self, etfs):
            self._etfs = etfs

        def get_etf_pool(self):
            return self._etfs

    return _P(codes)


def _etf(code, status="active"):
    return ETF(code=code, name=code, exchange="SH", etf_type="A股",
               theme="其他", status=status)


def test_universe_whitelist_akshare_mode(screening, monkeypatch):
    """akshare 模式下，扫描小池应被收敛为白名单交集。"""
    monkeypatch.setattr("config.settings.DATA_SOURCE", "akshare")
    monkeypatch.setattr("config.settings.USE_WHITELIST_POOL", True)
    monkeypatch.setattr("config.settings.ETF_WHITELIST", ["510300.SH", "512880.SH", "999999.SH"])

    pool = [_etf("510300.SH"), _etf("512880.SH"), _etf("159915.SZ"), _etf("588000.SH")]
    provider = _fake_provider_with_pool(pool)
    # 用假 provider 替换 screening 内的数据源
    screening.mock = provider

    universe = screening.get_scan_universe()
    codes = {e.code for e in universe}
    assert codes == {"510300.SH", "512880.SH"}   # 只保留命中白名单的
    assert "159915.SZ" not in codes


def test_universe_full_pool_mock_mode(screening, monkeypatch):
    """mock 模式下即使启用白名单，也应返回全池（不影响测试/演示）。"""
    monkeypatch.setattr("config.settings.DATA_SOURCE", "mock")
    monkeypatch.setattr("config.settings.USE_WHITELIST_POOL", True)
    monkeypatch.setattr("config.settings.ETF_WHITELIST", ["510300.SH"])

    pool = [_etf("510300.SH"), _etf("159915.SZ"), _etf("588000.SH")]
    provider = _fake_provider_with_pool(pool)
    screening.mock = provider

    universe = screening.get_scan_universe()
    assert len(universe) == 3   # 全池，白名单被忽略
    assert {e.code for e in universe} == {"510300.SH", "159915.SZ", "588000.SH"}


def test_universe_whitelist_empty_fallback(screening, monkeypatch):
    """白名单与池无交集时回退全池，避免空扫描。"""
    monkeypatch.setattr("config.settings.DATA_SOURCE", "akshare")
    monkeypatch.setattr("config.settings.USE_WHITELIST_POOL", True)
    monkeypatch.setattr("config.settings.ETF_WHITELIST", ["000000.SH"])

    pool = [_etf("510300.SH"), _etf("159915.SZ")]
    provider = _fake_provider_with_pool(pool)
    screening.mock = provider

    universe = screening.get_scan_universe()
    assert len(universe) == 2   # 回退全池


# --------------------------------------------------------------------------
# PersistentKlineStore
# --------------------------------------------------------------------------
def _make_klines(code="510300.SH", n=70, last_date="2026-07-14"):
    klines = []
    base = _dt.strptime(last_date, "%Y-%m-%d")
    for i in range(n):
        d = base - timedelta(days=(n - 1 - i))
        klines.append(DailyKline(
            etf_code=code, trade_date=d.strftime("%Y-%m-%d"),
            open=1.0, high=1.1, low=0.9, close=1.0 + i * 0.001,
            volume=1000.0, amount=1000.0,
        ))
    return klines


def test_kline_store_roundtrip(tmp_path):
    """写入后读取应还原等价的 DailyKline 列表。"""
    store = PersistentKlineStore(str(tmp_path / "klines"))
    # 固定"最近交易日"为缓存数据的最新日期，避免被真实系统日期判为过期
    store.latest_trading_day = lambda: "2026-07-14"
    kl = _make_klines()
    store.put("510300.SH", kl)

    got = store.get("510300.SH")
    assert got is not None
    assert len(got) == len(kl)
    assert got[-1].trade_date == kl[-1].trade_date
    assert got[0].close == kl[0].close
    assert store.stats()["cached_symbols"] == 1


def test_kline_store_freshness_stale(tmp_path):
    """缓存最新交易日早于"最近交易日"应判定为过期，返回 None（触发重拉）。"""
    store = PersistentKlineStore(str(tmp_path / "klines"))
    kl = _make_klines(last_date="2026-07-13")
    store.put("510300.SH", kl)

    # 把"最近交易日"伪装成 07-14（晚于缓存的 07-13）→ 缓存过期
    store.latest_trading_day = lambda: "2026-07-14"
    assert store.get("510300.SH") is None


def test_kline_store_freshness_fresh(tmp_path):
    """缓存最新交易日 >= 最近交易日应视为新鲜，直接命中。"""
    store = PersistentKlineStore(str(tmp_path / "klines"))
    kl = _make_klines(last_date="2026-07-14")
    store.put("510300.SH", kl)

    store.latest_trading_day = lambda: "2026-07-14"
    assert store.get("510300.SH") is not None


def test_kline_store_empty_noop(tmp_path):
    """空 K 线写入应为安全 no-op，不产生缓存条目。"""
    store = PersistentKlineStore(str(tmp_path / "klines"))
    store.put("510300.SH", [])
    assert store.get("510300.SH") is None
    assert store.stats()["cached_symbols"] == 0


def test_kline_store_latest_trading_day_weekend():
    """周末应回退到上周五。"""
    import src.infrastructure.kline_cache as kc

    # 2026-07-18 是周六 → 应返回 2026-07-17（周五）
    FakeDateTime._now = _dt(2026, 7, 18, 12, 0)
    saved = kc.datetime
    kc.datetime = FakeDateTime
    try:
        assert PersistentKlineStore.latest_trading_day() == "2026-07-17"
    finally:
        kc.datetime = saved
        FakeDateTime._now = None
