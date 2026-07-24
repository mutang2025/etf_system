"""AKShare data provider with rate limiting and circuit breaker protection.

Implements the same interface as MockDataProvider:
- get_etf_pool() → list[ETF]
- get_active_etfs() → list[ETF]
- get_klines(code, days) → list[DailyKline]
- get_realtime_quote(code) → dict | None
- get_all_realtime_quotes() → list[dict]
- update_realtime() → refresh quotes (min 60s interval)
- get_hs300_klines(days) → list[DailyKline]
- get_hs300_today_change() → float

Data sources:
- fund_etf_spot_em()        → 东方财富, realtime quotes + market cap
- fund_etf_fund_daily_em()   → 东方财富, ETF type classification
- fund_etf_hist_sina()       → 新浪, daily K-line OHLCV
- stock_zh_index_daily()     → 新浪, HS300 index K-line

Protection layers:
- RateLimiter: enforces min interval between calls per source
- CircuitBreaker: auto-trips after N consecutive failures, blocks requests
                  during cooldown, then allows one test request (half-open)
- update_realtime: hard minimum 60s between refreshes
- All network errors gracefully degrade to cached/stale data
"""

import time
import random
import math
import logging
from datetime import datetime, timedelta
from typing import Optional, Callable
import numpy as np
import pandas as pd

from src.domain.entities import ETF, DailyKline
from src.infrastructure.rate_limiter import (
    rate_limiter,
    breaker_spot_em, breaker_daily_em,
    breaker_hist_sina, breaker_index_sina,
    RATE_LIMITS, get_health_status,
)
from src.infrastructure.kline_cache import PersistentKlineStore
from config import settings

logger = logging.getLogger("akshare_provider")

# 数据告警回调（可注入到外部监控系统）；失败时触发。
_data_alert_callback: Optional[Callable[[str], None]] = None


def set_data_alert_callback(fn: Optional[Callable[[str], None]]) -> None:
    """设置数据异常告警回调（如推送到钉钉/企业微信/日志平台）。"""
    global _data_alert_callback
    _data_alert_callback = fn


# Theme keyword mapping — derive theme from ETF name
THEME_KEYWORDS = {
    "芯片半导体": ["芯片", "半导体", "集成电路", "科创芯片"],
    "新能源": ["新能源", "新能源车", "碳中和", "电池", "光伏", "锂电"],
    "医药": ["医药", "医疗", "生物", "创新药", "中药"],
    "消费": ["消费", "食品饮料", "白酒", "零售", "商贸"],
    "金融": ["证券", "券商", "银行", "金融", "保险"],
    "科技": ["科技", "人工智能", "AI", "信息", "软件", "云计算", "5G", "通信"],
    "军工": ["军工", "国防", "军事"],
    "光伏": ["光伏", "太阳能", "新能源发电"],
    "创业板": ["创业板", "创50", "创蓝筹"],
    "沪深300": ["沪深300", "300ETF", "沪深三百"],
    "跨境": ["纳指", "标普", "恒生", "中概", "日经", "德国", "法国", "亚太"],
    "有色": ["有色", "金属", "矿业", "钢铁", "煤炭", "稀土"],
    "房地产": ["房地产", "地产", "基建", "建材"],
    "农业": ["农业", "养殖", "种植", "粮食"],
}

# ETF types from fund_etf_fund_daily_em that should be excluded
EXCLUDED_TYPE_KEYWORDS = ["固收", "货币", "债券", "LOF"]


class AKShareDataProvider:
    """Fetches real ETF market data via AKShare with protection layers."""

    def __init__(self):
        import akshare as ak
        self._ak = ak
        self._rng = np.random.RandomState(42)  # For buy_signal.py compatibility
        self._random = random.Random(42)

        # Caches
        self._etf_pool: list[ETF] = []
        self._etf_map: dict[str, ETF] = {}
        self._realtime_cache: dict[str, dict] = {}
        self._kline_cache: dict[str, list[DailyKline]] = {}
        self._kline_store = PersistentKlineStore()   # 落盘 K 线缓存（跨重启持久）
        self._hs300_klines: list[DailyKline] = []

        # Timestamps for rate-limit aware methods
        self._last_realtime_update: float = 0
        # 最近一次数据告警（供健康检查暴露）
        self._last_alert: Optional[str] = None

        # Load data
        self._load_etf_pool()
        self._load_realtime_quotes()
        self._load_hs300()

    def _code_to_sina_symbol(self, code: str) -> str:
        """Convert ETF code to sina symbol format.
        510300 → sh510300, 159915 → sz159915
        """
        bare = code.replace(".SH", "").replace(".SZ", "")
        if bare.startswith(("5", "6")):
            return f"sh{bare}"
        else:
            return f"sz{bare}"

    def _alert(self, msg: str) -> None:
        """记录数据异常告警（logging + 外部回调 + 健康检查可见）。"""
        logger.error(msg)
        self._last_alert = msg
        if _data_alert_callback:
            try:
                _data_alert_callback(msg)
            except Exception:
                pass

    def _add_exchange_suffix(self, bare_code: str) -> str:
        """Add .SH or .SZ suffix to bare code."""
        if bare_code.startswith(("5", "6")):
            return f"{bare_code}.SH"
        else:
            return f"{bare_code}.SZ"

    def _classify_theme(self, name: str) -> str:
        """Classify ETF theme by name keywords."""
        for theme, keywords in THEME_KEYWORDS.items():
            for kw in keywords:
                if kw in name:
                    return theme
        return "其他"

    def _is_cross_border(self, etf_type: str, name: str) -> str:
        """Determine if ETF is cross-border type."""
        if "海外" in etf_type or any(kw in name for kw in ["纳指", "标普", "恒生", "中概", "日经", "德国", "法国"]):
            return "跨境"
        return "A股"

    def _should_exclude(self, etf_type: str) -> bool:
        """Check if ETF type should be excluded (bond/currency/LOF)."""
        for kw in EXCLUDED_TYPE_KEYWORDS:
            if kw in etf_type:
                return True
        return False

    # ============ Protected API calls ============

    def _fetch_spot_em(self) -> Optional[pd.DataFrame]:
        """Fetch fund_etf_spot_em with rate limiter + circuit breaker."""
        if not breaker_spot_em.can_proceed():
            print("[AKShare] spot_em circuit OPEN — skipping, using cache", flush=True)
            return None

        rate_limiter.wait_if_needed("eastmoney_spot", RATE_LIMITS["eastmoney_spot"])
        try:
            df = self._ak.fund_etf_spot_em()
            breaker_spot_em.on_success()
            return df
        except Exception as e:
            breaker_spot_em.on_failure(str(e)[:120])
            self._alert(f"[AKShare] spot_em 实时行情获取失败: {e}")
            return None

    def _fetch_daily_em(self) -> Optional[pd.DataFrame]:
        """Fetch fund_etf_fund_daily_em with rate limiter + circuit breaker."""
        if not breaker_daily_em.can_proceed():
            print("[AKShare] daily_em circuit OPEN — skipping, using cache", flush=True)
            return None

        rate_limiter.wait_if_needed("eastmoney_daily", RATE_LIMITS["eastmoney_daily"])
        try:
            df = self._ak.fund_etf_fund_daily_em()
            breaker_daily_em.on_success()
            return df
        except Exception as e:
            breaker_daily_em.on_failure(str(e)[:120])
            self._alert(f"[AKShare] daily_em 获取失败: {e}")
            return None

    def _fetch_kline_sina(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch fund_etf_hist_sina with rate limiter + circuit breaker."""
        if not breaker_hist_sina.can_proceed():
            print(f"[AKShare] sina kline circuit OPEN — skipping {symbol}", flush=True)
            return None

        rate_limiter.wait_if_needed("sina_kline", RATE_LIMITS["sina_kline"])
        try:
            df = self._ak.fund_etf_hist_sina(symbol=symbol)
            breaker_hist_sina.on_success()
            return df
        except Exception as e:
            breaker_hist_sina.on_failure(str(e)[:120])
            self._alert(f"[AKShare] sina K线获取失败 {symbol}: {e}")
            return None

    def _fetch_index_sina(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch stock_zh_index_daily with rate limiter + circuit breaker."""
        if not breaker_index_sina.can_proceed():
            print("[AKShare] sina index circuit OPEN — skipping", flush=True)
            return None

        rate_limiter.wait_if_needed("sina_index", RATE_LIMITS["sina_index"])
        try:
            df = self._ak.stock_zh_index_daily(symbol=symbol)
            breaker_index_sina.on_success()
            return df
        except Exception as e:
            breaker_index_sina.on_failure(str(e)[:120])
            self._alert(f"[AKShare] sina 指数获取失败: {e}")
            return None

    # ============ Data loading methods ============

    def _load_etf_pool(self) -> None:
        """Load ETF pool from spot_em + daily_em, with graceful degradation."""
        print("[AKShare] Loading ETF pool...", flush=True)

        spot_df = self._fetch_spot_em()
        if spot_df is None:
            print("[AKShare] Cannot load ETF pool — spot_em unavailable", flush=True)
            return

        print(f"[AKShare] Spot data: {len(spot_df)} ETFs", flush=True)

        daily_df = self._fetch_daily_em()
        type_map: dict[str, str] = {}
        if daily_df is not None:
            for _, row in daily_df.iterrows():
                code = str(row["基金代码"]).strip()
                etf_type = str(row["类型"]).strip()
                type_map[code] = etf_type

        now_str = datetime.now().strftime("%Y-%m-%d")

        for _, row in spot_df.iterrows():
            bare_code = str(row["代码"]).strip()
            if not bare_code.isdigit() or len(bare_code) != 6:
                continue

            code = self._add_exchange_suffix(bare_code)
            name = str(row["名称"]).strip()
            etf_type_raw = type_map.get(bare_code, "指数型-股票")

            etf_type = self._is_cross_border(etf_type_raw, name)
            theme = self._classify_theme(name)
            should_exclude = self._should_exclude(etf_type_raw)

            try:
                total_market_cap = float(row.get("总市值", 0) or 0) / 1e8
            except (ValueError, TypeError):
                total_market_cap = 0.0

            try:
                turnover = float(row.get("成交额", 0) or 0) / 1e4
            except (ValueError, TypeError):
                turnover = 0.0

            avg_amount_20d = turnover
            list_date = "2020-01-01"
            status = "excluded" if should_exclude else "active"

            # 白名单小池：被点名的 ETF 直接置为 whitelist 状态，Layer1 基础过滤直通，
            # 不受流动性/市值门槛影响（这些是我们主动要跟踪的标的）。
            if settings.USE_WHITELIST_POOL and code in set(settings.ETF_WHITELIST):
                status = "whitelist"

            etf = ETF(
                code=code, name=name,
                exchange="SH" if code.endswith(".SH") else "SZ",
                etf_type=etf_type, track_index=None, theme=theme,
                list_date=list_date,
                avg_amount_20d=round(avg_amount_20d, 2),
                total_market_cap=round(total_market_cap, 2),
                status=status, data_status="normal", synced_date=now_str,
            )
            self._etf_pool.append(etf)
            self._etf_map[code] = etf

        active_count = sum(1 for e in self._etf_pool if e.status == "active")
        print(f"[AKShare] ETF pool loaded: {len(self._etf_pool)} total, {active_count} active", flush=True)

    def _load_realtime_quotes(self) -> None:
        """Refresh realtime quote cache from spot_em."""
        spot_df = self._fetch_spot_em()
        if spot_df is None:
            self._alert("[AKShare] 实时行情刷新失败，使用缓存/空数据")
            return

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for _, row in spot_df.iterrows():
            bare_code = str(row["代码"]).strip()
            if not bare_code.isdigit() or len(bare_code) != 6:
                continue
            code = self._add_exchange_suffix(bare_code)

            try:
                price = float(row.get("最新价", 0) or 0)
                change_pct = float(row.get("涨跌幅", 0) or 0)
                volume = float(row.get("成交量", 0) or 0) / 100
                amount = float(row.get("成交额", 0) or 0) / 1e4
                open_price = float(row.get("开盘价", 0) or 0)
                high = float(row.get("最高价", 0) or 0)
                low = float(row.get("最低价", 0) or 0)
                prev_close = float(row.get("昨收", 0) or 0)
                volume_ratio = float(row.get("量比", 0) or 0)
            except (ValueError, TypeError):
                continue

            if price <= 0:
                continue

            quote = {
                "code": code,
                "name": str(row.get("名称", "")).strip(),
                "price": round(price, 4),
                "change_pct": round(change_pct, 2),
                "volume": round(volume, 2),
                "amount": round(amount, 2),
                "open": round(open_price, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "prev_close": round(prev_close, 4),
                "volume_ratio": round(volume_ratio, 2),
                "timestamp": now_str,
            }
            # 真实行情里个别 ETF（如新股无昨收）会给出 inf/nan 的涨跌幅，
            # 这些非有限浮点无法被 JSON 序列化（FastAPI 会 500）。
            # 统一兜底为 None，避免整批行情接口崩溃。
            for k, v in quote.items():
                if isinstance(v, float) and not math.isfinite(v):
                    quote[k] = None

            self._realtime_cache[code] = quote

        self._last_realtime_update = time.time()
        print(f"[AKShare] Realtime quotes loaded: {len(self._realtime_cache)} ETFs", flush=True)

    def _load_hs300(self) -> None:
        """Load HS300 index K-line from sina."""
        print("[AKShare] Loading HS300 index data...", flush=True)
        df = self._fetch_index_sina("sh000300")
        if df is not None:
            klines: list[DailyKline] = []
            for _, row in df.iterrows():
                date = str(row["date"]).strip()
                kline = DailyKline(
                    etf_code="000300.SH", trade_date=date,
                    open=round(float(row["open"]), 2),
                    high=round(float(row["high"]), 2),
                    low=round(float(row["low"]), 2),
                    close=round(float(row["close"]), 2),
                    volume=round(float(row["volume"]), 2),
                    amount=0.0,
                )
                klines.append(kline)
            self._hs300_klines = klines
            print(f"[AKShare] HS300 loaded: {len(klines)} days", flush=True)
        else:
            print("[AKShare] HS300 load failed, will use ETF proxy", flush=True)

    # ============ Interface methods ============

    def get_etf_pool(self) -> list[ETF]:
        """Return the full ETF pool."""
        return self._etf_pool

    def get_active_etfs(self) -> list[ETF]:
        """Return only active ETFs."""
        return [e for e in self._etf_pool if e.status == "active"]

    def get_klines(self, etf_code: str, days: int = 120) -> list[DailyKline]:
        """Return daily K-line data for an ETF.

        Cache hierarchy (fastest → slowest):
        1. in-process ``_kline_cache`` (lost on restart)
        2. on-disk ``_kline_store``   (persists across restarts — the perf win)
        3. network fetch from sina    (rate-limited + circuit-breakered), then write back to both
        """
        # 1) in-process cache — but ONLY if still fresh.
        # ⚠️ 之前这里直接返回，不做新鲜度检查，导致进程内缓存一旦写入就
        # 在整个后端进程生命周期内永远返回旧 K 线（直到重启），表现为
        # 「持仓看板弹框 K 线不更新 / 比 ETF 池陈旧」。
        # 现在与磁盘缓存用同一套新鲜度口径：最新交易日才认为有效。
        if etf_code in self._kline_cache:
            klines = self._kline_cache[etf_code]
            if klines and klines[-1].trade_date >= PersistentKlineStore.latest_trading_day():
                return klines[-days:] if days < len(klines) else klines
            # 过期 → 落到磁盘/网络层重新抓取

        # 2) persistent on-disk cache (auto-refreshes once per trading day)
        cached = self._kline_store.get(etf_code)
        if cached is not None:
            self._kline_cache[etf_code] = cached
            return cached[-days:] if days < len(cached) else cached

        # 3) network fetch with protection
        sina_symbol = self._code_to_sina_symbol(etf_code)
        df = self._fetch_kline_sina(sina_symbol)
        if df is not None:
            klines: list[DailyKline] = []
            for _, row in df.iterrows():
                date = str(row["date"]).strip()
                kline = DailyKline(
                    etf_code=etf_code, trade_date=date,
                    open=round(float(row["open"]), 4),
                    high=round(float(row["high"]), 4),
                    low=round(float(row["low"]), 4),
                    close=round(float(row["close"]), 4),
                    volume=round(float(row["volume"]) / 100, 2),
                    amount=round(float(row["amount"]) / 1e4, 2),
                )
                klines.append(kline)
            self._kline_cache[etf_code] = klines
            self._kline_store.put(etf_code, klines)   # persist for next restart
            print(f"[AKShare] K-line loaded+persisted: {etf_code} {len(klines)} days", flush=True)
            return klines[-days:] if days < len(klines) else klines

        # Circuit open or failed — return empty
        return []

    def get_realtime_quote(self, etf_code: str) -> Optional[dict]:
        """Return real-time quote snapshot for an ETF."""
        return self._realtime_cache.get(etf_code)

    def get_all_realtime_quotes(self) -> list[dict]:
        """Return all real-time quotes."""
        return list(self._realtime_cache.values())

    def update_realtime(self) -> bool:
        """Refresh realtime quotes from AKShare.

        Enforced minimum 60 seconds between refreshes.
        Returns True if refresh was attempted, False if throttled.
        """
        min_interval = RATE_LIMITS.get("update_realtime", 60)
        elapsed = time.time() - self._last_realtime_update

        if elapsed < min_interval and self._last_realtime_update > 0:
            remaining = min_interval - elapsed
            print(f"[AKShare] update_realtime throttled: {remaining:.0f}s until next allowed (min {min_interval}s)", flush=True)
            return False

        try:
            self._load_realtime_quotes()
            return True
        except Exception as e:
            self._alert(f"[AKShare] 实时行情更新失败: {e}")
            return False

    def get_hs300_klines(self, days: int = 120) -> list[DailyKline]:
        """Return HS300 index K-line data."""
        if not self._hs300_klines:
            self._load_hs300()
        if days < len(self._hs300_klines):
            return self._hs300_klines[-days:]
        return self._hs300_klines

    def get_hs300_today_change(self) -> float:
        """Return today's change percentage of HS300."""
        klines = self.get_hs300_klines(2)
        if len(klines) >= 2:
            prev = klines[-2].close
            curr = klines[-1].close
            return round((curr - prev) / prev * 100, 2)

        # Fallback: use 510300 ETF change as proxy
        rt = self.get_realtime_quote("510300.SH")
        if rt:
            return rt["change_pct"]
        return 0.0

    # ============ Health monitoring ============

    def get_health_status(self) -> dict:
        """Get health status of all data sources and protection layers."""
        health = get_health_status()

        # Add provider-level info
        health["cache"] = {
            "etf_pool": len(self._etf_pool),
            "active_etfs": len([e for e in self._etf_pool if e.status == "active"]),
            "kline_cached": len(self._kline_cache),
            "kline_persistent_cached": self._kline_store.stats()["cached_symbols"],
            "realtime_cached": len(self._realtime_cache),
            "hs300_klines": len(self._hs300_klines),
        }
        health["last_realtime_update"] = (
            datetime.fromtimestamp(self._last_realtime_update).strftime("%H:%M:%S")
            if self._last_realtime_update else None
        )
        health["realtime_update_min_interval_sec"] = RATE_LIMITS.get("update_realtime", 60)
        # 数据告警（P1-4）：最近一次失败原因，None 表示健康
        health["data_alert"] = self._last_alert

        # Calculate time until next allowed update
        if self._last_realtime_update > 0:
            elapsed = time.time() - self._last_realtime_update
            min_interval = RATE_LIMITS.get("update_realtime", 60)
            if elapsed < min_interval:
                health["realtime_update_available_in_sec"] = round(min_interval - elapsed)
            else:
                health["realtime_update_available_in_sec"] = 0
        else:
            health["realtime_update_available_in_sec"] = 0

        return health


# Singleton
_akshare_provider: Optional[AKShareDataProvider] = None


def get_akshare_provider() -> AKShareDataProvider:
    """Get or create the singleton AKShare data provider."""
    global _akshare_provider
    if _akshare_provider is None:
        _akshare_provider = AKShareDataProvider()
    return _akshare_provider
