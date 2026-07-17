"""Centralized Shanghai (CST, UTC+8) timezone-aware "now".

The trading system is anchored to China A-share hours, so every
business-logic timestamp must be CST — not the server's local wall clock
(which may be UTC inside a container and would skew "today", hold-days,
and sell-cooldown math across midnight).

History: some modules used ``datetime.now()`` (naive, server-local) and
others ``datetime.now(CST)`` (aware). Mixing the two is both
inconsistent and a latent ``TypeError`` whenever an aware datetime is
subtracted from a naive one. This module is the single source of truth.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

# Asia/Shanghai == China Standard Time (UTC+8), no DST.
CST = ZoneInfo("Asia/Shanghai")


def now_cst() -> datetime:
    """Current time as a timezone-aware datetime in Asia/Shanghai (UTC+8)."""
    return datetime.now(CST)
