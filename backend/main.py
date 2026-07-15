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

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="ETF动量轮动选股系统 - 四层漏斗筛选 + 实时买卖信号 + 持仓管理",
)

# CORS: allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Dev only; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(router)


@app.on_event("startup")
async def startup_event():
    """Initialize database and sync mock data on startup."""
    print("[Startup] Initializing database...")
    conn = init_db()
    print("[Startup] Database initialized with WAL mode")

    # Initialize default params
    db = DatabaseRepository(conn)
    db.init_default_params()
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


@app.on_event("shutdown")
async def shutdown_event():
    """Stop the realtime scanner daemon on shutdown."""
    try:
        get_scanner().stop()
        print("[Shutdown] Realtime scanner daemon stopped")
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
