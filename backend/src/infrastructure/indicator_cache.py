"""Process-wide indicator cache — eliminates the per-round N+1 recompute.

Problem
-------
``IndicatorCalculator.get_all_indicators()`` runs ~10 rolling pandas/numpy
computations over a 120-day K-line window. It is invoked on *every*
scan round for *every* ETF from several independent call sites:

  * ``screening_engine``  — layer2 multi-factor scoring (once/day) *and*
    layer4 risk filter, which re-computes what layer2 already did
    (intra-run N+1).
  * ``sell_strategies``   — per holding, every ~10s daemon round.
  * ``position_manager``    — ``update_all_positions`` per holding per round,
    plus ``confirm_buy``; both re-derive ``is_trend_stock`` from scratch.
  * ``buy_signal``         — per layer4 candidate, every round. The P2
    "scan-universe widening" expanded this set from ~2 to ~11 ETFs, which
    is exactly what *would* have amplified the old N+1 recompute.

Daily K-lines change at most once per trading day (realtime ticks only
update the *quote*, never the daily bars). So the indicator result is
stable for an entire session. We key the cache by
``(etf_code, days, last_trade_date)`` — when a new daily bar lands the
key changes and the entry auto-misses, no manual eviction required.

This is orthogonal to, and *complementary* with, the scan-universe
widening: widening multiplies how many ETFs each round touches; the cache
flattens that back to exactly one computation per ETF per day, regardless
of how many rounds or call sites request it.

Why a process-wide singleton (not a per-provider cache)
---------------------------------------------------
The raw K-line fetch is *already* cached inside each provider
(``_kline_cache`` / ``PersistentKlineStore``). What was missing is the
*derived* layer — indicator computation — and it must be shared across
all four call sites to actually collapse the N+1. A single module-level
singleton gives every caller the same hit rate.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Optional

from src.indicators.technical import IndicatorCalculator

# Canonical window used by every call site. Centralized so a single change
# keeps the cache key consistent across screening / buy / sell / position paths.
DEFAULT_INDICATOR_DAYS: int = 120


class IndicatorCache:
    """In-process cache of indicator dicts, keyed by (code, days, last_date).

    Thread-safe: the realtime daemon runs on its own thread and the API
    serves on the uvicorn worker thread(s), so every public method takes
    the lock.
    """

    def __init__(self, max_size: int = 5000):
        # ordered so we can evict least-recently-used when over capacity
        self._data: "OrderedDict[tuple, dict]" = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._max_size = max_size

    # ------------------------------------------------------------------ core
    def get(self, provider, etf_code: str, days: int = DEFAULT_INDICATOR_DAYS) -> dict:
        """Return cached indicators for ``etf_code``, computing on a miss.

        Returns ``{}`` when K-lines are missing/insufficient. On a hit the
        cached dict is *shallow-copied* so a caller cannot corrupt the
        shared object (nested MACD/BB dicts are never mutated by callers).
        """
        klines = provider.get_klines(etf_code, days)
        if not klines or len(klines) < 2:
            return {}

        last_date = klines[-1].trade_date
        key = (etf_code, days, last_date)

        with self._lock:
            if key in self._data:
                self._hits += 1
                return dict(self._data[key])

        # miss → (re)compute once
        indicators = IndicatorCalculator(klines).get_all_indicators()

        with self._lock:
            self._misses += 1
            self._data[key] = indicators
            self._data.move_to_end(key)
            # LRU eviction if we blew past capacity
            while len(self._data) > self._max_size:
                self._data.popitem(last=False)

        return dict(indicators)

    def is_trend_stock(self, provider, etf_code: str, days: int = DEFAULT_INDICATOR_DAYS) -> bool:
        """Trend-stock flag derived from the cached indicators (no recompute)."""
        return bool(self.get(provider, etf_code, days).get("is_trend_stock", False))

    # --------------------------------------------------------------- management
    def invalidate_code(self, etf_code: str) -> None:
        """Drop every cached entry for a single ETF (e.g., on a forced refresh)."""
        with self._lock:
            for key in [k for k in self._data if k[0] == etf_code]:
                del self._data[key]

    def invalidate(self) -> None:
        """Clear the entire cache."""
        with self._lock:
            self._data.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict:
        """Observability counters for the health endpoint."""
        with self._lock:
            return {
                "size": len(self._data),
                "hits": self._hits,
                "misses": self._misses,
                "max_size": self._max_size,
                "hit_rate": round(self._hits / (self._hits + self._misses), 4)
                if (self._hits + self._misses) else 0.0,
            }


# Process-wide singleton — every call site shares the same cache instance.
_indicator_cache: Optional[IndicatorCache] = None


def get_indicator_cache() -> IndicatorCache:
    """Return the process-wide indicator cache (lazily created)."""
    global _indicator_cache
    if _indicator_cache is None:
        _indicator_cache = IndicatorCache()
    return _indicator_cache


# Convenience module-level helpers so call sites don't have to thread the
# cache instance everywhere — they just pass the data provider.
def get_cached_indicators(provider, etf_code: str, days: int = DEFAULT_INDICATOR_DAYS) -> dict:
    """Cached ``IndicatorCalculator(klines).get_all_indicators()``."""
    return get_indicator_cache().get(provider, etf_code, days)


def is_trend_stock_cached(provider, etf_code: str, days: int = DEFAULT_INDICATOR_DAYS) -> bool:
    """Cached ``is_trend_stock`` flag (derived from cached indicators)."""
    return get_indicator_cache().is_trend_stock(provider, etf_code, days)
