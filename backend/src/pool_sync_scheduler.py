"""ETF pool auto-sync scheduler — 交易日收盘后自动同步一次。

运维诉求：ETF 池元数据（列表、成交额、市值等）不应只在「首次启动」或「手动点按钮」时更新，
应在每个交易日收盘后自动刷新一次，确保盘中新增/剔除的 ETF、市值变化等能落地到数据库。

本模块在应用启动时（按 POOL_SYNC_ENABLED 开关）拉起一个 asyncio 后台循环：
- 每分钟检查一次当前时间（固定 Asia/Shanghai 时区）
- 当且仅当「当天是工作日 且 当前时间已越过 POOL_SYNC_AFTER（默认收盘后 15:30） 且 今日尚未同步过」时，
  触发一次 db.sync_etf_pool()
- 用 _last_synced_date 记录最近成功同步的自然日，保证每个自然日最多同步一次（跨日自动失效）

交易日采用与 routes.py / market_indices.py 统一的工作日近似（weekday()<5），不含法定节假日；
如需精确到交易日历可后续接入 akshare 交易日历（会引入网络依赖，与 mock 离线开发理念冲突，故保持工作日近似）。
"""

import asyncio
from datetime import datetime
from typing import Optional

from config import settings
from src.infrastructure.timeutil import CST
from src.infrastructure.database_repo import DatabaseRepository


# 后台循环的检查间隔（秒）。每分钟检查一次足够——同步只在收盘后触发一次。
CHECK_INTERVAL_SECONDS = 60


class PoolSyncScheduler:
    """Background loop that auto-syncs the ETF pool once per trading day after market close."""

    def __init__(self):
        self.db = DatabaseRepository()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.sync_count = 0
        self.started_at: Optional[str] = None
        self.last_sync: Optional[dict] = None
        self.last_error: Optional[str] = None
        # 记录最近一次成功同步的自然日（YYYY-MM-DD）；跨日自动失效，保证每日最多一次
        self._last_synced_date: Optional[str] = None

    # ---------- control ----------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    def is_running(self) -> bool:
        return self._running

    # ---------- gate ----------
    def _should_sync_now(self) -> bool:
        """判定此刻是否应触发一次池同步。"""
        now = datetime.now(CST)
        # 1) 交易日近似：周一到周五（不含法定节假日，与项目现有写法统一）
        if now.weekday() >= 5:  # Sat/Sun
            return False
        # 2) 当前时间已越过「收盘后触发时刻」
        after = datetime.strptime(settings.POOL_SYNC_AFTER, "%H:%M").time()
        if now.time() < after:
            return False
        # 3) 今日尚未同步过（避免一天多次触发）
        today = now.strftime("%Y-%m-%d")
        if self._last_synced_date == today:
            return False
        return True

    # ---------- main loop ----------
    async def _loop(self) -> None:
        self.started_at = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
        while self._running:
            try:
                if self._should_sync_now():
                    await self._do_sync()
            except asyncio.CancelledError:
                break
            except Exception as e:  # keep the loop alive
                self.last_error = f"{datetime.now(CST).strftime('%H:%M:%S')} {type(e).__name__}: {e}"
                print(f"[PoolSync] error: {self.last_error}")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    async def _do_sync(self) -> None:
        # sync_etf_pool 是同步 DB 操作，放到线程里跑避免阻塞事件循环
        result = await asyncio.to_thread(self.db.sync_etf_pool)
        self.sync_count += 1
        self._last_synced_date = datetime.now(CST).strftime("%Y-%m-%d")
        self.last_sync = {
            "sync_count": self.sync_count,
            "timestamp": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
            "result": result,
        }
        print(f"[PoolSync] ETF pool synced after close (#{self.sync_count}): {result}")

    # ---------- status ----------
    def get_status(self) -> dict:
        return {
            "running": self._running,
            "sync_count": self.sync_count,
            "started_at": self.started_at,
            "enabled": settings.POOL_SYNC_ENABLED,
            "sync_after": settings.POOL_SYNC_AFTER,
            "check_interval_seconds": CHECK_INTERVAL_SECONDS,
            "last_synced_date": self._last_synced_date,
            "last_sync": self.last_sync,
            "last_error": self.last_error,
        }


# ---------- singleton ----------
_scheduler: Optional[PoolSyncScheduler] = None


def get_pool_sync_scheduler() -> PoolSyncScheduler:
    """Module-level singleton, same pattern as get_scanner()."""
    global _scheduler
    if _scheduler is None:
        _scheduler = PoolSyncScheduler()
    return _scheduler
