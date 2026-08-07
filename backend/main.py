"""ETF Quantitative Trading System - FastAPI Main Application.

Run: uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

import os
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from config import settings
from database import init_db
from src.presentation.routes import router
from src.infrastructure.database_repo import DatabaseRepository
from src.realtime_scanner import get_scanner
from src.pool_sync_scheduler import get_pool_sync_scheduler
from src.screening_scheduler import get_screening_scheduler
from src.infrastructure.market_indices import get_index_provider

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="ETF动量轮动选股系统 - 四层漏斗筛选 + 实时买卖信号 + 持仓管理",
)

# CORS：受信源默认本地开发服务器；一旦设置 API_TOKEN 则强制收紧到白名单并启用凭据。
_origins_raw = settings.CORS_ALLOWED_ORIGINS or ""
_allowed_origins = [o.strip() for o in _origins_raw.split(",") if o.strip()]
if settings.API_TOKEN:
    # 安全模式：收紧到白名单，禁止 "*" + credentials 的非法组合
    allow_origins = _allowed_origins or ["http://localhost:3001"]
    allow_credentials = True
    print(f"[CORS] Secure mode: restricted to {allow_origins}")
else:
    # 本地开发：开放所有源（凭据关闭，避免 "*" + credentials 非法组合）
    allow_origins = ["*"]
    allow_credentials = False
    print("[CORS] Open mode (no API_TOKEN set): allow all origins, credentials disabled")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(router)

# P3 回测框架（只读分析端点，不修改持仓/信号）
from src.backtest.api import router as backtest_router
app.include_router(backtest_router)


@app.on_event("startup")
async def startup_event():
    """Initialize database and sync mock data on startup."""
    print("[Startup] Initializing database...")
    conn = init_db()
    print("[Startup] Database initialized with WAL mode")

    # Initialize default params
    db = DatabaseRepository(conn)
    db.init_default_params()
    # 把库内策略参数加载进内存 config.settings，使引擎读取用户调优值（修 P0-1）
    db.load_params_into_settings()
    print("[Startup] Default strategy parameters initialized")

    # Sync ETF pool on first run
    pool_count = len(db.get_etf_pool())
    if pool_count == 0:
        print("[Startup] First run: syncing ETF pool from mock data...")
        result = db.sync_etf_pool()
        print(f"[Startup] ETF pool synced: {result}")
    else:
        print(f"[Startup] ETF pool already has {pool_count} ETFs")

    print(f"[Startup] {settings.APP_NAME} v{settings.APP_VERSION} ready on port {settings.PORT}")

    # 启动盘中自动扫描守护进程（PRD: 每 N 秒自动扫描+推送信号）
    if settings.SCANNER_ENABLED:
        try:
            get_scanner().start()
            print(f"[Startup] Realtime scanner daemon started (interval={settings.SCAN_INTERVAL_SECONDS}s)")
        except Exception as e:
            print(f"[Startup] Failed to start scanner daemon: {e}")

    # 启动 ETF 池定时同步守护进程（交易日收盘后自动同步一次）
    if settings.POOL_SYNC_ENABLED:
        try:
            get_pool_sync_scheduler().start()
            print(f"[Startup] ETF pool sync scheduler started (after_close={settings.POOL_SYNC_AFTER})")
        except Exception as e:
            print(f"[Startup] Failed to start pool sync scheduler: {e}")

    # 启动四层选股定时调度器（交易日收盘后自动跑一次选股并入池）
    if settings.SCREENING_ENABLED:
        try:
            get_screening_scheduler().start()
            print(f"[Startup] Screening scheduler started (after_close={settings.SCREENING_AFTER})")
        except Exception as e:
            print(f"[Startup] Failed to start screening scheduler: {e}")

    # 启动指数行情后台保活（交易看板 / Dashboard 指数区永远命中热缓存，消除冷启动 ~1.5s）
    try:
        get_index_provider().start_background_refresh()
        print("[Startup] Index quotes background refresh started")
    except Exception as e:
        print(f"[Startup] Failed to start index refresh: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Stop the daemon loops on shutdown."""
    try:
        get_scanner().stop()
        print("[Shutdown] Realtime scanner daemon stopped")
    except Exception:
        pass
    try:
        get_pool_sync_scheduler().stop()
        print("[Shutdown] ETF pool sync scheduler stopped")
    except Exception:
        pass
    try:
        get_screening_scheduler().stop()
        print("[Shutdown] Screening scheduler stopped")
    except Exception:
        pass
    try:
        get_index_provider().stop_background_refresh()
        print("[Shutdown] Index quotes background refresh stopped")
    except Exception:
        pass


@app.get("/")
async def root():
    """Root endpoint - serve frontend if available, otherwise API info."""
    frontend_path = Path(__file__).parent.parent / "frontend" / "dist" / "index.html"
    if frontend_path.exists():
        return FileResponse(frontend_path)
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "api": "/api",
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "version": settings.APP_VERSION}


# Serve frontend static files if dist exists
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """SPA fallback for BrowserRouter client-side routes.

    /api/*, /assets, /docs and /health are matched by earlier routes, so this
    only catches unmatched GETs (e.g. a hard refresh on /signals => index.html).
    """
    frontend_index = Path(__file__).parent.parent / "frontend" / "dist" / "index.html"
    if frontend_index.exists():
        return FileResponse(frontend_index)
    return {"detail": "Frontend not built. Run `npm run build` in frontend/."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
