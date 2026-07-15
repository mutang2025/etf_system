"""Mock data provider that generates realistic ETF market data.

Generates:
- ETF pool (~200 ETFs across 10+ themes)
- Daily K-line data (120 trading days history)
- Real-time quotes snapshot
- 沪深300 index data
- Theme/sector classification mapping
"""

import random
import sqlite3
from datetime import datetime, timedelta
from typing import Optional
import numpy as np

from src.domain.entities import ETF, DailyKline
from config import settings


# Theme definitions with representative ETFs
THEME_MAP = {
    "芯片半导体": [
        ("512480.SH", "半导体ETF"),
        ("512760.SH", "芯片ETF"),
        ("159995.SZ", "芯片ETF"),
        ("516620.SH", "芯片ETF基金"),
        ("588800.SH", "科创芯片ETF"),
    ],
    "新能源": [
        ("516160.SH", "新能源ETF"),
        ("515030.SH", "新能源车ETF"),
        ("159875.SZ", "新能源车ETF"),
        ("516850.SH", "新能源ETF基金"),
        ("562860.SH", "光伏ETF"),
    ],
    "医药": [
        ("512010.SH", "医药ETF"),
        ("159929.SZ", "医药ETF"),
        ("513050.SH", "中概互联ETF"),
        ("512170.SH", "医疗ETF"),
        ("159823.SZ", "医疗ETF"),
    ],
    "消费": [
        ("510150.SH", "消费ETF"),
        ("159928.SZ", "消费ETF"),
        ("515170.SH", "食品饮料ETF"),
        ("159938.SZ", "消费ETF基金"),
        ("515080.SH", "消费ETF"),
    ],
    "金融": [
        ("512880.SH", "证券ETF"),
        ("512000.SH", "券商ETF"),
        ("515020.SH", "银行ETF"),
        ("512800.SH", "银行ETF"),
        ("159993.SZ", "证券ETF"),
    ],
    "科技": [
        ("512050.SH", "AI ETF"),
        ("515000.SH", "科技ETF"),
        ("159732.SZ", "科技ETF"),
        ("515760.SH", "人工智能ETF"),
        ("515950.SH", "科技龙头ETF"),
    ],
    "军工": [
        ("512660.SH", "军工ETF"),
        ("512660.SH", "军工ETF基金"),
        ("515610.SH", "国防ETF"),
        ("159992.SZ", "军工ETF"),
        ("515070.SH", "军工ETF"),
    ],
    "光伏": [
        ("515790.SH", "光伏ETF"),
        ("516620.SH", "碳中和ETF"),
        ("159853.SZ", "光伏ETF"),
        ("562860.SH", "光伏50ETF"),
        ("515100.SH", "新能源ETF基金"),
    ],
    "创业板": [
        ("159915.SZ", "创业板ETF"),
        ("159977.SZ", "创业板ETF基金"),
        ("515950.SH", "创业板ETF"),
        ("159952.SZ", "创业板ETF"),
        ("516050.SH", "创业板50ETF"),
    ],
    "沪深300": [
        ("510300.SH", "沪深300ETF"),
        ("510310.SH", "沪深300ETF基金"),
        ("510330.SH", "沪深300ETF增强"),
        ("159919.SZ", "沪深300ETF"),
        ("515100.SH", "沪深300增强ETF"),
    ],
    "跨境": [
        ("513050.SH", "中概互联ETF"),
        ("513100.SH", "纳指ETF"),
        ("513180.SH", "恒生科技ETF"),
        ("513520.SH", "日经ETF"),
        ("159941.SZ", "纳指ETF"),
    ],
    "有色": [
        ("512400.SH", "有色金属ETF"),
        ("515050.SH", "有色金属ETF基金"),
        ("159871.SZ", "有色金属ETF"),
        ("516650.SH", "矿业ETF"),
        ("515220.SH", "钢铁ETF"),
    ],
    "食品饮料": [
        ("515170.SH", "食品饮料ETF"),
        ("159843.SZ", "食品饮料ETF基金"),
        ("515080.SH", "消费ETF基金"),
    ],
    "煤炭": [
        ("515220.SH", "煤炭ETF"),
        ("516220.SH", "煤炭ETF基金"),
        ("159898.SZ", "煤炭ETF"),
    ],
    "房地产": [
        ("512200.SH", "房地产ETF"),
        ("515060.SH", "房地产ETF基金"),
        ("510710.SH", "房地产ETF"),
    ],
}

# Bond/monetary ETFs to be excluded (for testing layer 1)
EXCLUDED_TYPES = [
    ("511010.SH", "国债ETF", "债券型"),
    ("511260.SH", "十年国债ETF", "债券型"),
    ("511880.SH", "银华日利ETF", "货币型"),
    ("511990.SH", "华宝添益ETF", "货币型"),
    ("161006.SZ", "LOF基金A", "LOF"),
    ("161005.SZ", "LOF基金B", "LOF"),
]


class MockDataProvider:
    """Generates and provides mock ETF market data."""

    def __init__(self, seed: int = 42):
        self._rng = np.random.RandomState(seed)
        self._random = random.Random(seed)
        self._etf_pool: list[ETF] = []
        self._kline_cache: dict[str, list[DailyKline]] = {}
        self._realtime_cache: dict[str, dict] = {}
        self._generate_pool()
        self._generate_klines()
        self._generate_realtime()

    def _generate_pool(self) -> None:
        """Generate the full ETF pool with all themes."""
        seen_codes = set()

        # Generate real ETFs from theme map
        for theme, etfs in THEME_MAP.items():
            for code, name in etfs:
                if code in seen_codes:
                    continue
                seen_codes.add(code)

                exchange = "SH" if code.endswith(".SH") else "SZ"
                etf_type = "A股"
                if theme == "跨境":
                    etf_type = "跨境"

                # Generate realistic market cap and volume
                cap = self._random.uniform(10, 500)
                amount_20d = self._random.uniform(500, 50000)
                list_date = self._random.choice([
                    "2020-01-15", "2021-03-20", "2022-06-10",
                    "2023-09-01", "2024-12-15", "2025-03-01"
                ])

                # Add some low liquidity/small cap ETFs for filter testing
                if self._random.random() < 0.15:
                    cap = self._random.uniform(5, 50)
                    amount_20d = self._random.uniform(500, 2500)

                etf = ETF(
                    code=code,
                    name=name,
                    exchange=exchange,
                    etf_type=etf_type,
                    track_index=self._get_track_index(theme, code),
                    theme=theme,
                    list_date=list_date,
                    avg_amount_20d=round(amount_20d, 2),
                    total_market_cap=round(cap, 2),
                    status="active",
                    data_status="normal",
                    synced_date=datetime.now().strftime("%Y-%m-%d"),
                )
                self._etf_pool.append(etf)

        # Add excluded types (bond/monetary/LOF)
        for code, name, _type in EXCLUDED_TYPES:
            exchange = "SH" if code.endswith(".SH") else "SZ"
            etf = ETF(
                code=code,
                name=name,
                exchange=exchange,
                etf_type="A股",
                track_index=None,
                theme="债券/货币/LOF",
                list_date="2020-01-01",
                avg_amount_20d=round(self._random.uniform(1000, 10000), 2),
                total_market_cap=round(self._random.uniform(50, 200), 2),
                status="excluded",
                data_status="normal",
                synced_date=datetime.now().strftime("%Y-%m-%d"),
            )
            self._etf_pool.append(etf)

        # Generate additional synthetic ETFs to reach ~200
        themes_list = list(THEME_MAP.keys())
        for i in range(len(self._etf_pool), 200):
            theme = self._random.choice(themes_list)
            exchange = self._random.choice(["SH", "SZ"])
            code_num = self._random.randint(500000, 599999)
            code = f"{code_num}.{exchange}"
            if code in seen_codes:
                continue
            seen_codes.add(code)

            cap = self._random.uniform(20, 300)
            amount_20d = self._random.uniform(2000, 30000)

            etf = ETF(
                code=code,
                name=f"{theme}ETF{code_num}",
                exchange=exchange,
                etf_type="A股" if theme != "跨境" else "跨境",
                track_index=f"{theme}指数",
                theme=theme,
                list_date=self._random.choice([
                    "2021-06-01", "2022-03-15", "2023-01-20",
                    "2024-09-10", "2025-05-01"
                ]),
                avg_amount_20d=round(amount_20d, 2),
                total_market_cap=round(cap, 2),
                status="active",
                data_status="normal",
                synced_date=datetime.now().strftime("%Y-%m-%d"),
            )
            self._etf_pool.append(etf)

    def _get_track_index(self, theme: str, code: str) -> str:
        """Get tracking index name for a theme."""
        index_map = {
            "芯片半导体": "国证芯片指数",
            "新能源": "中证新能源指数",
            "医药": "中证医药卫生指数",
            "消费": "中证主要消费指数",
            "金融": "中证全指证券公司指数",
            "科技": "中证科技龙头指数",
            "军工": "中证军工指数",
            "光伏": "中证光伏产业指数",
            "创业板": "创业板指数",
            "沪深300": "沪深300指数",
            "跨境": "纳斯达克100/恒生科技指数",
            "有色": "中证有色金属指数",
            "食品饮料": "中证食品饮料指数",
            "煤炭": "中证煤炭指数",
            "房地产": "中证房地产指数",
        }
        return index_map.get(theme, "未分类指数")

    def _generate_klines(self) -> None:
        """Generate 120 trading days of K-line data for each active ETF."""
        end_date = datetime.now()
        trading_days = self._get_trading_days(end_date, 120)

        for etf in self._etf_pool:
            if etf.status == "excluded":
                continue

            klines: list[DailyKline] = []
            # Random starting price between 0.5 and 5.0
            base_price = self._random.uniform(0.5, 5.0)
            # Random trend: some uptrend, some downtrend, some sideways
            trend_type = self._rng.choice(["up", "down", "sideways"], p=[0.4, 0.25, 0.35])
            trend_strength = self._random.uniform(0.001, 0.003)

            prev_close = base_price
            for i, day in enumerate(trading_days):
                if trend_type == "up":
                    drift = trend_strength
                elif trend_type == "down":
                    drift = -trend_strength
                else:
                    drift = 0.0

                daily_return = self._rng.normal(drift, 0.02)
                close = prev_close * (1 + daily_return)
                close = max(close, 0.1)

                open_price = prev_close * (1 + self._rng.normal(0, 0.005))
                open_price = max(open_price, 0.1)
                high = max(open_price, close) * (1 + abs(self._rng.normal(0, 0.008)))
                low = min(open_price, close) * (1 - abs(self._rng.normal(0, 0.008)))
                # Volume in lots (手)
                base_vol = self._random.uniform(50000, 5000000)
                volume = base_vol * (1 + abs(self._rng.normal(0, 0.3)))
                # Amount in 万元
                price = (open_price + close) / 2
                amount = volume * price / 10  # convert to 万元

                kline = DailyKline(
                    etf_code=etf.code,
                    trade_date=day,
                    open=round(open_price, 4),
                    high=round(high, 4),
                    low=round(low, 4),
                    close=round(close, 4),
                    volume=round(volume, 2),
                    amount=round(amount, 2),
                )
                klines.append(kline)
                prev_close = close

            self._kline_cache[etf.code] = klines

    def _generate_realtime(self) -> None:
        """Generate real-time quote snapshot for all active ETFs."""
        for etf in self._etf_pool:
            if etf.status == "excluded":
                continue
            klines = self._kline_cache.get(etf.code, [])
            if not klines:
                continue
            last = klines[-1]
            # Real-time price fluctuates around last close
            rt_change = self._rng.normal(0, 0.015)
            rt_price = last.close * (1 + rt_change)
            rt_volume = last.volume * self._random.uniform(0.3, 0.8)

            # 真实量比：近5日均量 / 前15日均量（确定性，基于历史K线）
            vols = [k.volume for k in klines[-20:]]
            if len(vols) >= 20 and sum(vols[-20:-5]) > 0:
                vol_ratio = (sum(vols[-5:]) / 5) / (sum(vols[-20:-5]) / 15)
            else:
                vol_ratio = 1.0

            self._realtime_cache[etf.code] = {
                "code": etf.code,
                "name": etf.name,
                "price": round(rt_price, 4),
                "change_pct": round(rt_change * 100, 2),
                "volume": round(rt_volume, 2),
                "volume_ratio": round(float(vol_ratio), 2),
                "amount": round(rt_volume * rt_price / 10, 2),
                "open": last.open,
                "high": max(last.high, rt_price),
                "low": min(last.low, rt_price),
                "prev_close": last.close,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

    def _get_trading_days(self, end_date: datetime, count: int) -> list[str]:
        """Generate `count` trading days (skip weekends)."""
        days: list[str] = []
        current = end_date
        while len(days) < count:
            if current.weekday() < 5:  # Mon-Fri
                days.insert(0, current.strftime("%Y-%m-%d"))
            current -= timedelta(days=1)
        return days

    def get_etf_pool(self) -> list[ETF]:
        """Return the full ETF pool."""
        return self._etf_pool

    def get_active_etfs(self) -> list[ETF]:
        """Return only active ETFs (passed basic filter criteria)."""
        return [e for e in self._etf_pool if e.status == "active"]

    def get_klines(self, etf_code: str, days: int = 120) -> list[DailyKline]:
        """Return daily K-line data for an ETF."""
        klines = self._kline_cache.get(etf_code, [])
        if days < len(klines):
            return klines[-days:]
        return klines

    def get_realtime_quote(self, etf_code: str) -> Optional[dict]:
        """Return real-time quote snapshot for an ETF."""
        return self._realtime_cache.get(etf_code)

    def get_all_realtime_quotes(self) -> list[dict]:
        """Return all real-time quotes."""
        return list(self._realtime_cache.values())

    def update_realtime(self) -> None:
        """Simulate a tick: update all real-time quotes slightly."""
        for code in list(self._realtime_cache.keys()):
            rt = self._realtime_cache[code]
            tick_change = self._rng.normal(0, 0.002)
            new_price = rt["price"] * (1 + tick_change)
            new_price = max(new_price, 0.05)
            prev_price = rt["price"]
            rt["price"] = round(new_price, 4)
            rt["change_pct"] = round(rt["change_pct"] + tick_change * 100, 2)
            rt["high"] = max(rt["high"], new_price)
            rt["low"] = min(rt["low"], new_price)
            rt["volume"] = round(rt["volume"] + abs(self._rng.normal(1000, 5000)), 2)
            rt["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def get_hs300_klines(self, days: int = 120) -> list[DailyKline]:
        """Return mock 沪深300 index K-line data."""
        end_date = datetime.now()
        trading_days = self._get_trading_days(end_date, days)
        klines: list[DailyKline] = []
        base = 3500.0
        prev_close = base
        for day in trading_days:
            daily_return = self._rng.normal(0, 0.012)
            close = prev_close * (1 + daily_return)
            open_price = prev_close * (1 + self._rng.normal(0, 0.005))
            high = max(open_price, close) * (1 + abs(self._rng.normal(0, 0.006)))
            low = min(open_price, close) * (1 - abs(self._rng.normal(0, 0.006)))
            volume = self._random.uniform(100000000, 500000000)

            kline = DailyKline(
                etf_code="000300.SH",
                trade_date=day,
                open=round(open_price, 2),
                high=round(high, 2),
                low=round(low, 2),
                close=round(close, 2),
                volume=round(volume, 2),
                amount=round(volume * close / 10, 2),
            )
            klines.append(kline)
            prev_close = close
        return klines

    def get_hs300_today_change(self) -> float:
        """Return today's change percentage of 沪深300."""
        klines = self.get_hs300_klines(2)
        if len(klines) < 2:
            return 0.0
        prev = klines[-2].close
        curr = klines[-1].close
        return round((curr - prev) / prev * 100, 2)


# Singleton instance
_mock_provider: Optional[MockDataProvider] = None


def get_mock_provider() -> MockDataProvider:
    """Get or create the singleton mock data provider."""
    global _mock_provider
    if _mock_provider is None:
        _mock_provider = MockDataProvider()
    return _mock_provider
