"""交易看板 - 多指数行情数据源。

覆盖指数：
    上证指数 / 深证成指 / 创业板指 / 科创50 / 沪深300 / 上证50 / 北证50 / 恒生指数（港股）

数据获取策略（与系统其余部分保持一致）：
- 若 settings.DATA_SOURCE == "akshare" 且 AKShare 可联网，则拉取新浪指数行情
  （stock_zh_index_daily / stock_zh_index_spot_sina）；
- 否则（本地开发 / 离线 / 网络受限）自动降级为确定性 mock 生成器，
  保证「交易看板」始终可渲染、可演示。

mock 生成器特性（只用于离线/开发，不影响生产真实数据路径）：
- K 线历史由「指数代码」作为随机种子，跨请求与重启保持稳定（图表不会乱跳）；
- 当日实时价在「昨日收盘」基础上叠加时间驱动的轻微波动（±1.5%），
  刷新时呈现“活”的盘口，但数值始终合理。
"""

import math
import random
import time
from datetime import datetime, timedelta
from typing import Optional

from config import settings

# 指数定义：code 内部代码, name 中文名, sina 新浪符号, base 基准点位, color 主题色
INDEX_DEFS = [
    {"code": "000001.SH", "name": "上证指数", "sina": "sh000001", "base": 3210.0, "color": "#ef4444"},
    {"code": "399001.SZ", "name": "深证成指", "sina": "sz399001", "base": 10150.0, "color": "#f59e0b"},
    {"code": "399006.SZ", "name": "创业板指", "sina": "sz399006", "base": 2050.0, "color": "#8b5cf6"},
    {"code": "000688.SH", "name": "科创50",   "sina": "sh000688", "base": 880.0,  "color": "#06b6d4"},
    {"code": "000300.SH", "name": "沪深300",  "sina": "sh000300", "base": 3850.0, "color": "#10b981"},
    {"code": "000016.SH", "name": "上证50",   "sina": "sh000016", "base": 2650.0, "color": "#3b82f6"},
    {"code": "899050.BJ", "name": "北证50",   "sina": "bj899050", "base": 1100.0, "color": "#ec4899"},
    {"code": "HSI.HK",    "name": "恒生指数", "sina": "HSI", "base": 17800.0, "color": "#f97316", "market": "hk"},
]

_DEF_BY_CODE = {d["code"]: d for d in INDEX_DEFS}
_DEF_BY_SINA = {d["sina"]: d for d in INDEX_DEFS}


def _seed_for(code: str) -> int:
    """Stable integer seed derived from the index code."""
    h = 0
    for ch in code:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h


class IndexDataProvider:
    """Multi-index quote + K-line source with akshare-first / mock-fallback."""

    def __init__(self):
        self._use_akshare = settings.DATA_SOURCE == "akshare"
        self._ak = None
        if self._use_akshare:
            try:
                import akshare as ak
                self._ak = ak
            except Exception:
                self._ak = None
                self._use_akshare = False

        # caches
        self._kline_cache: dict[str, list] = {}
        self._spot_cache: Optional[dict] = None
        self._spot_updated = 0.0
        self._spot_ttl = 30.0  # seconds — realtime quotes re-fetched at most every 30s

    # ============================================================== mock
    def _mock_klines(self, code: str, days: int) -> list:
        """Deterministic daily K-line history seeded by the index code."""
        if code in self._kline_cache:
            cached = self._kline_cache[code]
            return cached[-days:] if days < len(cached) else cached

        rng = random.Random(_seed_for(code))
        base = _DEF_BY_CODE.get(code, {"base": 3000.0})["base"]
        total = max(days, 180)
        closes: list[float] = []
        price = base * 0.9
        for _ in range(total):
            step = rng.gauss(0, 0.013)
            pull = (base - price) / base * 0.02  # gentle pull toward base
            price *= 1 + step + pull
            closes.append(price)

        scale = base / closes[-1]
        closes = [c * scale for c in closes]

        klines: list[dict] = []
        # Collect `total` trading-day dates ending TODAY (inclusive), then align to closes.
        back: list[datetime] = []
        d = datetime.now()
        while len(back) < total:
            if d.weekday() < 5:  # skip weekends -> looks like trading days
                back.append(d)
            d -= timedelta(days=1)
        dates = list(reversed(back))  # oldest -> today
        for i, dd in enumerate(dates):
            close = round(closes[i], 2)
            op = round(close * (1 + rng.gauss(0, 0.004)), 2)
            hi = round(max(op, close) * (1 + abs(rng.gauss(0, 0.005))), 2)
            lo = round(min(op, close) * (1 - abs(rng.gauss(0, 0.005))), 2)
            vol = int(rng.uniform(2.0e9, 5.0e9))
            klines.append({
                "trade_date": dd.strftime("%Y-%m-%d"),
                "open": op, "high": hi, "low": lo,
                "close": close, "volume": vol,
            })

        self._kline_cache[code] = klines
        return klines[-days:] if days < len(klines) else klines

    def _live_jitter(self, code: str) -> float:
        """Time-driven small drift for 'today' so the board feels live (bounded ±1.5%)."""
        now = datetime.now()
        secs = now.hour * 3600 + now.minute * 60 + now.second
        wave = math.sin(secs / 5400.0) * 0.008  # slow wave across a trading day
        rnd = random.Random(_seed_for(code) + now.minute).uniform(-0.004, 0.004)
        return max(-0.015, min(0.015, wave + rnd))

    def _mock_quote(self, code: str) -> dict:
        klines = self._mock_klines(code, 120)
        prev = klines[-2]["close"]
        last_hist = klines[-1]["close"]
        jitter = self._live_jitter(code)
        price = round(last_hist * (1 + jitter), 2)
        change = round(price - prev, 2)
        pct = round((price - prev) / prev * 100, 2)
        op = round(prev * (1 + random.Random(_seed_for(code) + 99).uniform(-0.003, 0.004)), 2)
        hi = round(max(price, op) * (1 + abs(random.Random(_seed_for(code) + 1).gauss(0, 0.004))), 2)
        lo = round(min(price, op) * (1 - abs(random.Random(_seed_for(code) + 2).gauss(0, 0.004))), 2)
        volume = int(random.Random(_seed_for(code) + 3).uniform(2.0e9, 5.0e9))
        amount = round(random.Random(_seed_for(code) + 4).uniform(2800.0, 5600.0), 1)  # 亿元
        return {
            "code": code,
            "name": _DEF_BY_CODE[code]["name"],
            "color": _DEF_BY_CODE[code]["color"],
            "price": price,
            "prev_close": prev,
            "open": op,
            "high": hi,
            "low": lo,
            "change": change,
            "change_pct": pct,
            "volume": volume,
            "amount": amount,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _mock_breadth(self) -> dict:
        """涨跌家数（市场宽度）——离线演示用，约每 30s 微调一次。"""
        rng = random.Random(int(time.time() // 30) + 777)
        up = rng.randint(1200, 2600)
        down = rng.randint(800, 2200)
        flat = rng.randint(80, 260)
        limit_up = rng.randint(20, 90)
        limit_down = rng.randint(5, 40)
        return {
            "up": up, "down": down, "flat": flat,
            "limit_up": limit_up, "limit_down": limit_down,
        }

    # ============================================================== akshare
    def _akshare_spot(self) -> Optional[dict]:
        """Fetch realtime index spot from sina; returns {sina_symbol_lower: row}."""
        if not self._ak:
            return None
        now = time.time()
        if self._spot_cache is not None and (now - self._spot_updated) < self._spot_ttl:
            return self._spot_cache
        try:
            df = self._ak.stock_zh_index_spot_sina()
            if df is None:
                return None
            by_symbol: dict = {}
            for _, row in df.iterrows():
                sym = str(row.get("代码", "")).strip().lower()
                by_symbol[sym] = row
            self._spot_cache = by_symbol
            self._spot_updated = now
            return by_symbol
        except Exception:
            return None

    def _akshare_index_daily(self, code: str, days: int) -> Optional[list]:
        if not self._ak:
            return None
        d = _DEF_BY_CODE.get(code)
        if not d:
            return None
        sina = d.get("sina")
        if not sina:
            return None
        try:
            # 港股（恒生）走独立新浪日K接口；A股走 stock_zh_index_daily
            if d.get("market") == "hk":
                df = self._ak.stock_hk_index_daily_sina(symbol=sina)
            else:
                df = self._ak.stock_zh_index_daily(symbol=sina)
            if df is None:
                return None
            klines: list[dict] = []
            for _, row in df.iterrows():
                klines.append({
                    "trade_date": str(row["date"]).strip(),
                    "open": round(float(row["open"]), 2),
                    "high": round(float(row["high"]), 2),
                    "low": round(float(row["low"]), 2),
                    "close": round(float(row["close"]), 2),
                    "volume": round(float(row.get("volume", 0) or 0), 2),
                })
            return klines[-days:] if days < len(klines) else klines
        except Exception:
            return None

    def _build_quote(self, d, price, prev, open_, high, low, pct, volume, amount) -> dict:
        """Assemble a standardized index quote dict."""
        return {
            "code": d["code"],
            "name": d["name"],
            "color": d["color"],
            "price": round(price, 2),
            "prev_close": round(prev, 2),
            "open": round(open_, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "change": round(price - prev, 2),
            "change_pct": round(pct, 2),
            "volume": int(volume),
            "amount": round(amount, 1),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _akshare_hk_quote(self, d: dict) -> Optional[dict]:
        """Realtime Hang Seng Index quote.

        Primary source: Sina HK index spot (stock_hk_index_spot_sina) — reliable
        and returns the full HK index list (filter by name). Fallback: daily
        K-line via stock_hk_index_daily_sina("HSI") so the board still shows a
        valid HSI quote even if the realtime spot API is unstable/offline.
        """
        if not self._ak:
            return None
        # 1) Sina HK index realtime spot
        try:
            df = self._ak.stock_hk_index_spot_sina()
            if df is not None and "名称" in getattr(df, "columns", []):
                row = df[df["名称"] == d["name"]]
                if len(row):
                    r = row.iloc[0]
                    price = float(r.get("最新价", 0) or 0)
                    prev = float(r.get("昨收", 0) or 0)
                    if price > 0 and prev > 0:
                        return self._build_quote(
                            d, price, prev,
                            float(r.get("今开", 0) or price),
                            float(r.get("最高", 0) or price),
                            float(r.get("最低", 0) or price),
                            float(r.get("涨跌幅", 0) or 0),
                            float(r.get("成交量", 0) or 0),
                            float(r.get("成交额", 0) or 0) / 1e8,
                        )
        except Exception:
            pass
        # 2) Fallback: daily K-line (last two closes -> daily change)
        try:
            klines = self._akshare_index_daily(d["code"], 5)
            if klines and len(klines) >= 2:
                last = klines[-1]["close"]
                prev = klines[-2]["close"]
                pct = (last - prev) / prev * 100
                return self._build_quote(
                    d, last, prev,
                    klines[-1].get("open", last),
                    klines[-1].get("high", last),
                    klines[-1].get("low", last),
                    pct,
                    klines[-1].get("volume", 0),
                    0.0,
                )
        except Exception:
            pass
        return None

    # ============================================================== public API
    def _quote_from_sina_row(self, d: dict, row) -> Optional[dict]:
        """Build a quote dict from a sina A-share spot row; None if unusable."""
        try:
            price = float(row.get("最新价", 0) or 0)
            prev = float(row.get("昨收", 0) or 0)
            if price <= 0 or prev <= 0:
                return None
            return {
                "code": d["code"],
                "name": d["name"],
                "color": d["color"],
                "price": round(price, 2),
                "prev_close": round(prev, 2),
                "open": round(float(row.get("今开", 0) or price), 2),
                "high": round(float(row.get("最高", 0) or price), 2),
                "low": round(float(row.get("最低", 0) or price), 2),
                "change": round(price - prev, 2),
                "change_pct": round(float(row.get("涨跌幅", 0) or 0), 2),
                "volume": int(float(row.get("成交量", 0) or 0)),
                "amount": round(float(row.get("成交额", 0) or 0) / 1e8, 1),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        except (ValueError, TypeError):
            return None

    def get_index_quotes(self) -> dict:
        """Return quotes for all configured indices + market breadth."""
        spot = self._akshare_spot() if self._use_akshare else None
        indices = []
        for d in INDEX_DEFS:
            market = d.get("market", "a")
            q = None
            if market == "hk":
                # 港股（恒生）走独立港股行情源
                if self._use_akshare:
                    q = self._akshare_hk_quote(d)
            else:
                if spot:
                    row = spot.get(d["sina"].lower())
                    if row is not None:
                        q = self._quote_from_sina_row(d, row)
            if q is None:
                q = self._mock_quote(d["code"])
            q["market"] = market
            indices.append(q)

        return {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trading_day": datetime.now().weekday() < 5,
            "data_source": "akshare" if self._use_akshare else "mock",
            "indices": indices,
            "breadth": self._mock_breadth(),
        }

    def get_index_klines(self, code: str, days: int = 60) -> dict:
        """Return K-line history for one index (real if available, else mock)."""
        if code not in _DEF_BY_CODE:
            return {"code": code, "name": "", "klines": []}
        klines = self._akshare_index_daily(code, days) if self._use_akshare else None
        if not klines:
            klines = self._mock_klines(code, days)
        return {
            "code": code,
            "name": _DEF_BY_CODE[code]["name"],
            "color": _DEF_BY_CODE[code]["color"],
            "klines": klines,
        }


# Singleton accessor
_provider: Optional[IndexDataProvider] = None


def get_index_provider() -> IndexDataProvider:
    """Get or create the singleton IndexDataProvider."""
    global _provider
    if _provider is None:
        _provider = IndexDataProvider()
    return _provider
