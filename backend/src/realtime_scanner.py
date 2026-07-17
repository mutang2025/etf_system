"""Realtime scanner daemon — the missing "auto watch" loop from the PRD.

PRD承诺：每 SCAN_INTERVAL_SECONDS 秒自动扫描买入/卖出信号并推送。原实现只有
一次性 REST 端点，没有调度器，必须人工点接口。本模块在应用启动时拉起一个
asyncio 后台循环，交易时段内周期性执行买入/卖出扫描，结果写入数据库（信号列表
自动出现）并通过 WebSocket 实时推送。
"""

import asyncio
from datetime import datetime
from typing import Optional

from config import settings
from src.infrastructure.timeutil import CST
from src.infrastructure.database_repo import DatabaseRepository
from src.infrastructure.data_provider_factory import get_data_provider
from src.screening.screening_engine import get_screening
from src.trading.buy_signal import BuySignalEngine
from src.trading.position_manager import PositionManager
from src.trading.scan_tasks import run_buy_scan, run_sell_scan


class RealtimeScanner:
    """Background loop that periodically scans for buy/sell signals."""

    def __init__(self):
        self.db = DatabaseRepository()
        # 与路由共享同一 ScreeningEngine 单例：手动「运行选股」使缓存失效后，
        # 守护进程下一轮买入扫描也会取到最新推荐（修复 P0-2）
        self.screening = get_screening()
        self.buy_engine = BuySignalEngine()
        self.pos_manager = PositionManager(self.db)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.scan_count = 0
        self.started_at: Optional[str] = None
        self.last_scan: Optional[dict] = None
        self.last_error: Optional[str] = None
        self._last_reset_date: Optional[str] = None
        self._subscribers: set[asyncio.Queue] = set()

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

    # ---------- trading-hours gate ----------
    def _in_trading_hours(self) -> bool:
        now = datetime.now(CST)
        if now.weekday() >= 5:  # Sat/Sun
            return False
        start = datetime.strptime(settings.TRADING_START, "%H:%M").time()
        end = datetime.strptime(settings.TRADING_END, "%H:%M").time()
        return start <= now.time() <= end

    # ---------- main loop ----------
    async def _loop(self) -> None:
        self.started_at = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
        while self._running:
            try:
                # 跨交易日重置日内跟踪状态（冲高回落/强制减仓计数器、买入保持计时）
                today = datetime.now().strftime("%Y-%m-%d")
                if self._last_reset_date != today:
                    self.pos_manager.sell_engine.reset_daily_trackers()
                    self.buy_engine._condition_hold.clear()
                    self._last_reset_date = today

                if self._in_trading_hours():
                    await self._do_scan()
            except asyncio.CancelledError:
                break
            except Exception as e:  # keep the loop alive
                self.last_error = f"{datetime.now().strftime('%H:%M:%S')} {type(e).__name__}: {e}"
                print(f"[Scanner] scan error: {self.last_error}")
            await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS)

    async def _do_scan(self) -> None:
        provider = get_data_provider()
        if hasattr(provider, "update_realtime"):
            await asyncio.to_thread(provider.update_realtime)

        buy = await asyncio.to_thread(
            run_buy_scan, self.screening, self.buy_engine, self.pos_manager, self.db
        )
        sell = await asyncio.to_thread(run_sell_scan, self.pos_manager)

        self.scan_count += 1
        self.last_scan = {
            "scan_count": self.scan_count,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "in_trading_hours": True,
            "buy": buy,
            "sell": sell,
        }
        await self._publish(self.last_scan)

    # ---------- status ----------
    def get_status(self) -> dict:
        universe_size = len(self.screening.get_scan_universe())
        return {
            "running": self._running,
            "scan_count": self.scan_count,
            "started_at": self.started_at,
            "in_trading_hours": self._in_trading_hours(),
            "scan_interval_seconds": settings.SCAN_INTERVAL_SECONDS,
            "universe_size": universe_size,
            "use_whitelist": settings.DATA_SOURCE == "akshare" and settings.USE_WHITELIST_POOL,
            "last_scan": self.last_scan,
            "last_error": self.last_error,
        }

    # ---------- websocket pub/sub ----------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def _publish(self, payload: dict) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # drop oldest? keep simple: skip


_scanner: Optional[RealtimeScanner] = None


def get_scanner() -> RealtimeScanner:
    """Process-wide singleton scanner."""
    global _scanner
    if _scanner is None:
        _scanner = RealtimeScanner()
    return _scanner
