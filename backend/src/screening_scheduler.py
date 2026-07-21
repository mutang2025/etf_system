"""四层选股自动调度器 —— 交易日收盘后自动跑一次四层选股。

运维诉求：四层选股（layer1-4 漏斗）此前只能在前端手动点「运行选股」触发，
容易忘。应在每个交易日收盘后自动跑一次，把当日最终推荐 ETF 写入 selection_results
并自动纳入待买入池（run_screening 内部已实现入池逻辑），与手动触发完全等价。

本模块在应用启动时（按 SCREENING_ENABLED 开关）拉起一个 asyncio 后台循环：
- 每分钟检查一次当前时间（固定 Asia/Shanghai 时区）
- 当且仅当「当天是工作日 且 当前时间已越过 SCREENING_AFTER（默认收盘后 15:30）
  且 今日尚未自动跑过」时，触发一次 run_screening()
- 用 _last_run_date 记录最近成功运行的自然日，保证每个自然日最多跑一次（跨日自动失效）

与 PoolSyncScheduler 同构；run_screening 是 async 函数，直接 await 即可，
其内部已有 await 让出点，不会永久阻塞事件循环。调度器感知不到「手动触发」，
但 run_screening 内部对同日期先 clear 再写，手动/自动幂等，不会重复入池。

交易日采用与 routes.py / market_indices.py / pool_sync_scheduler.py 统一的工作日近似
（weekday()<5），不含法定节假日；如需精确到交易日历可后续接入 akshare 交易日历。
"""

import asyncio
from datetime import datetime
from typing import Optional

from config import settings
from src.infrastructure.timeutil import CST


# 后台循环的检查间隔（秒）。每分钟检查一次足够——选股只在收盘后触发一次。
CHECK_INTERVAL_SECONDS = 60


class ScreeningScheduler:
    """Background loop that auto-runs the four-layer screening once per trading day after close."""

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.run_count = 0
        self.started_at: Optional[str] = None
        self.last_run: Optional[dict] = None
        self.last_error: Optional[str] = None
        # 记录最近一次成功运行的自然日（YYYY-MM-DD）；跨日自动失效，保证每日最多一次
        self._last_run_date: Optional[str] = None

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
    def _should_run_now(self) -> bool:
        """判定此刻是否应触发一次自动选股。"""
        now = datetime.now(CST)
        # 1) 交易日近似：周一到周五（不含法定节假日，与项目现有写法统一）
        if now.weekday() >= 5:  # Sat/Sun
            return False
        # 2) 当前时间已越过「收盘后触发时刻」
        after = datetime.strptime(settings.SCREENING_AFTER, "%H:%M").time()
        if now.time() < after:
            return False
        # 3) 今日尚未自动跑过（避免一天多次触发，节省行情配额）
        today = now.strftime("%Y-%m-%d")
        if self._last_run_date == today:
            return False
        return True

    # ---------- main loop ----------
    async def _loop(self) -> None:
        self.started_at = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
        while self._running:
            try:
                if self._should_run_now():
                    await self._do_screening()
            except asyncio.CancelledError:
                break
            except Exception as e:  # keep the loop alive
                self.last_error = f"{datetime.now(CST).strftime('%H:%M:%S')} {type(e).__name__}: {e}"
                print(f"[ScreeningScheduler] error: {self.last_error}")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    async def _do_screening(self) -> None:
        # 延迟 import，避免模块加载期的循环依赖（routes 已在 main 启动时加载）
        from src.presentation import routes
        result = await routes.run_screening()
        self.run_count += 1
        self._last_run_date = datetime.now(CST).strftime("%Y-%m-%d")
        self.last_run = {
            "run_count": self.run_count,
            "timestamp": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
            "select_date": (result.get("summary") or {}).get("select_date"),
            "recommendations": len(result.get("recommendations", [])),
            "pool_added": result.get("pool_added", 0),
            "pool_skipped": result.get("pool_skipped", 0),
            "is_empty_signal": result.get("is_empty_signal", False),
        }
        print(f"[ScreeningScheduler] auto screening after close (#{self.run_count}): {self.last_run}")

    # ---------- status ----------
    def get_status(self) -> dict:
        return {
            "running": self._running,
            "run_count": self.run_count,
            "started_at": self.started_at,
            "enabled": settings.SCREENING_ENABLED,
            "screening_after": settings.SCREENING_AFTER,
            "check_interval_seconds": CHECK_INTERVAL_SECONDS,
            "last_run_date": self._last_run_date,
            "last_run": self.last_run,
            "last_error": self.last_error,
        }


# ---------- singleton ----------
_scheduler: Optional[ScreeningScheduler] = None


def get_screening_scheduler() -> ScreeningScheduler:
    """Module-level singleton, same pattern as get_scanner() / get_pool_sync_scheduler()."""
    global _scheduler
    if _scheduler is None:
        _scheduler = ScreeningScheduler()
    return _scheduler
