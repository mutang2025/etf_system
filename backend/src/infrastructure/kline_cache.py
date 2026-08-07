"""Persistent K-line cache on local disk.

Problem
-------
In real-data (akshare) mode the screening engine fetches daily K-lines for every
ETF in the pool. The full A-share ETF universe is ~1500 symbols, each requiring a
separate network call → a single screening pass can take many minutes and burns
through the data-source rate limit.

Fix
---
Layer the K-line cache with three tiers:

1. in-process dict (fastest, lost on restart)
2. **persistent on-disk JSON** (this module) — survives restarts, so a cold boot
   or a daily re-scan reuses already-downloaded history instead of re-fetching
   the whole market
3. network fetch (only when both caches miss)

Freshness
---------
Daily K-lines change at most once per trading day. We treat a cached entry as
*fresh* when its latest trade_date >= the most recent trading day
(weekends roll back to last Friday). Stale entries are ignored and re-fetched,
so the cache auto-refreshes once per day with zero manual intervention.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from config import settings
from src.domain.entities import DailyKline
from src.infrastructure.timeutil import CST


class PersistentKlineStore:
    """JSON-file backed K-line store, one file per ETF code + an index file."""

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir or settings.KLINE_CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)
        self._index_path = os.path.join(self.cache_dir, "_index.json")
        self._lock = threading.Lock()
        self._index = self._load_index()

    # ---------- index (latest_date per code) ----------
    def _load_index(self) -> dict:
        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_index(self) -> None:
        try:
            with open(self._index_path, "w", encoding="utf-8") as f:
                json.dump(self._index, f, ensure_ascii=False)
        except OSError:
            pass

    @staticmethod
    def _file_path(cache_dir: str, code: str) -> str:
        safe = code.replace(".", "_")
        return os.path.join(cache_dir, f"{safe}.json")

    # ---------- freshness ----------
    @staticmethod
    def latest_trading_day() -> str:
        """Return the most recent trading day whose daily bar is *expected to be
        published* (YYYY-MM-DD, China time / UTC+8).

        Daily A-share bars are only finalized after the 15:00 close, and the
        data source (sina/akshare) frequently lags by a while even then.
        Treating "today" as the freshness target therefore marks a perfectly
        good cache entry (still holding yesterday's bar) as *stale on every
        single call* during trading hours — forcing a full network re-fetch
        each time (observed: ~1s per ETF, ~3s for the positions page, which
        calls this path twice). To keep the on-disk / in-process K-line cache
        sticky we return:
          * the previous trading day while it is still a trading day and
            before ~16:00 CST (today's bar not yet reliably published), and
          * today (or last Friday on weekends) once the session has closed.
        This still refreshes the cache exactly once per day, right after close.
        """
        now = datetime.now(CST)
        if now.weekday() >= 5:  # Sat=5, Sun=6 → roll back to last Friday
            days_back = now.weekday() - 4
            return (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
        # weekday
        if now.hour < 16:  # before ~16:00 CST: today's bar not yet finalized
            d = now.date() - timedelta(days=1)
            while d.weekday() >= 5:  # skip across weekend if needed
                d -= timedelta(days=1)
            return d.strftime("%Y-%m-%d")
        return now.strftime("%Y-%m-%d")

    # ---------- public API ----------
    def get(self, code: str) -> Optional[list[DailyKline]]:
        """Return cached K-lines for ``code`` or ``None`` if missing/stale."""
        meta = self._index.get(code)
        if not meta:
            return None
        if meta.get("latest_date", "") < self.latest_trading_day():
            return None  # stale → caller must re-fetch

        path = self._file_path(self.cache_dir, code)
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return [DailyKline(**d) for d in raw]
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            return None

    def put(self, code: str, klines: list[DailyKline]) -> None:
        """Persist K-lines for ``code``. No-op for empty input."""
        if not klines:
            return
        latest_date = klines[-1].trade_date
        with self._lock:
            path = self._file_path(self.cache_dir, code)
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump([asdict(k) for k in klines], f, ensure_ascii=False)
                self._index[code] = {
                    "latest_date": latest_date,
                    "count": len(klines),
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                self._save_index()
            except OSError:
                pass

    def stats(self) -> dict:
        """Return cache statistics for health monitoring."""
        return {
            "cached_symbols": len(self._index),
            "dir": self.cache_dir,
        }
