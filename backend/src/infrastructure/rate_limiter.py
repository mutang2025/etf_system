"""Rate limiter and circuit breaker for AKShare API calls.

Implements two protection layers:
1. RateLimiter — enforces minimum intervals between calls to the same data source
2. CircuitBreaker — tracks consecutive failures, auto-degrades on repeated errors

States: CLOSED (normal) → OPEN (tripped, fail fast) → HALF_OPEN (testing recovery)
"""

import time
import threading
from datetime import datetime
from enum import Enum
from typing import Optional


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"        # Normal operation, requests pass through
    OPEN = "open"            # Tripped, requests fail fast / use fallback
    HALF_OPEN = "half_open"  # Testing if service recovered


class RateLimiter:
    """Enforces minimum interval between calls to the same source.

    Thread-safe via a simple lock.
    """

    def __init__(self):
        self._last_call: dict[str, float] = {}  # source -> last call timestamp
        self._lock = threading.Lock()

    def wait_if_needed(self, source: str, min_interval: float) -> None:
        """Block until enough time has passed since last call to this source."""
        with self._lock:
            last = self._last_call.get(source, 0)
            elapsed = time.time() - last
            if elapsed < min_interval and last > 0:
                sleep_time = min_interval - elapsed
                time.sleep(sleep_time)
            self._last_call[source] = time.time()

    def time_since_last(self, source: str) -> float:
        """Return seconds since last call to this source (inf if never called)."""
        last = self._last_call.get(source, 0)
        if last == 0:
            return float("inf")
        return time.time() - last


class CircuitBreaker:
    """Circuit breaker for a single data source.

    CLOSED  → consecutive failures reach threshold → OPEN
    OPEN    → cooldown passes → HALF_OPEN
    HALF_OPEN → next request succeeds → CLOSED
    HALF_OPEN → next request fails → OPEN (reset cooldown)
    """

    def __init__(self, name: str, failure_threshold: int = 3,
                 cooldown_seconds: float = 300):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

        self.state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at: Optional[float] = None  # timestamp when OPEN'd
        self._lock = threading.Lock()

        # Stats for health monitoring
        self.total_calls = 0
        self.total_failures = 0
        self.last_error: Optional[str] = None
        self.last_success_time: Optional[float] = None

    def can_proceed(self) -> bool:
        """Check if a request should be allowed through."""
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            elif self.state == CircuitState.OPEN:
                # Check if cooldown has passed
                if self._opened_at and time.time() - self._opened_at >= self.cooldown_seconds:
                    self.state = CircuitState.HALF_OPEN
                    return True  # Allow one test request
                return False  # Still in cooldown, fail fast
            elif self.state == CircuitState.HALF_OPEN:
                return True  # Allow test request

    def on_success(self):
        """Record a successful call."""
        with self._lock:
            self.total_calls += 1
            self._failure_count = 0
            self._success_count += 1
            self.last_success_time = time.time()
            if self.state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
                self.state = CircuitState.CLOSED
                self._opened_at = None

    def on_failure(self, error: str = ""):
        """Record a failed call."""
        with self._lock:
            self.total_calls += 1
            self.total_failures += 1
            self._failure_count += 1
            self.last_error = error
            if self.state == CircuitState.HALF_OPEN:
                # Test request failed, back to OPEN
                self.state = CircuitState.OPEN
                self._opened_at = time.time()
            elif self._failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self._opened_at = time.time()

    def get_status(self) -> dict:
        """Return current status for health monitoring."""
        with self._lock:
            cooldown_remaining = 0
            if self.state == CircuitState.OPEN and self._opened_at:
                cooldown_remaining = max(0, self.cooldown_seconds - (time.time() - self._opened_at))

            return {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self._failure_count,
                "failure_threshold": self.failure_threshold,
                "total_calls": self.total_calls,
                "total_failures": self.total_failures,
                "last_error": self.last_error,
                "last_success": datetime.fromtimestamp(self.last_success_time).strftime("%H:%M:%S")
                               if self.last_success_time else None,
                "cooldown_remaining_sec": round(cooldown_remaining),
            }

    def reset(self):
        """Manually reset the circuit breaker to CLOSED state."""
        with self._lock:
            self.state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None


# ============ Global instances ============

# Rate limiter for all API calls
rate_limiter = RateLimiter()

# Circuit breakers per data source
# Eastmoney sources (fund_etf_spot_em, fund_etf_fund_daily_em) — more sensitive
breaker_spot_em = CircuitBreaker("eastmoney_spot", failure_threshold=3, cooldown_seconds=300)
breaker_daily_em = CircuitBreaker("eastmoney_daily", failure_threshold=3, cooldown_seconds=300)

# Sina sources (fund_etf_hist_sina, stock_zh_index_daily) — more tolerant
breaker_hist_sina = CircuitBreaker("sina_kline", failure_threshold=5, cooldown_seconds=120)
breaker_index_sina = CircuitBreaker("sina_index", failure_threshold=5, cooldown_seconds=120)

# All breakers for health monitoring
ALL_BREAKERS = [breaker_spot_em, breaker_daily_em, breaker_hist_sina, breaker_index_sina]


# Minimum intervals between calls (seconds)
RATE_LIMITS = {
    "eastmoney_spot": 60.0,     # fund_etf_spot_em — 15 paginated requests, very heavy
    "eastmoney_daily": 30.0,   # fund_etf_fund_daily_em — lighter
    "sina_kline": 1.0,         # fund_etf_hist_sina — per-ETF K-line (1s safe for bulk fetch)
    "sina_index": 60.0,         # stock_zh_index_daily — index data
    "update_realtime": 60.0,    # minimum interval for update_realtime() calls
}


def get_health_status() -> dict:
    """Get health status of all data sources for monitoring."""
    return {
        "breakers": [b.get_status() for b in ALL_BREAKERS],
        "rate_limits": {k: v for k, v in RATE_LIMITS.items()},
    }
