"""Database setup with SQLite WAL mode for concurrent read/write."""

import sqlite3
from pathlib import Path
from typing import Optional
from config import settings


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create a SQLite connection with WAL mode and proper pragmas."""
    path = db_path or settings.DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Initialize database with all tables. Returns a connection."""
    conn = get_connection(db_path)
    _create_tables(conn)
    return conn


def _create_tables(conn: sqlite3.Connection) -> None:
    """Create all database tables from schema."""
    conn.executescript("""
    -- ETF pool table
    CREATE TABLE IF NOT EXISTS etf_pool (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        exchange TEXT NOT NULL,           -- SH / SZ
        etf_type TEXT NOT NULL,          -- A股 / 跨境
        track_index TEXT,                -- 跟踪指数
        theme TEXT,                      -- 题材分类
        list_date TEXT,                  -- 上市日期
        avg_amount_20d REAL,             -- 近20日日均成交额（万元）
        total_market_cap REAL,           -- 总市值（亿元）
        status TEXT DEFAULT 'active',    -- active / excluded / blacklist / whitelist
        data_status TEXT DEFAULT 'normal', -- normal / abnormal
        synced_date TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    -- Daily K-line data
    CREATE TABLE IF NOT EXISTS daily_kline (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        etf_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL,
        amount REAL NOT NULL,
        UNIQUE(etf_code, trade_date)
    );
    CREATE INDEX IF NOT EXISTS idx_kline_code_date ON daily_kline(etf_code, trade_date);

    -- Index daily data (沪深300 etc.)
    CREATE TABLE IF NOT EXISTS index_daily (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        index_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL,
        UNIQUE(index_code, trade_date)
    );

    -- Selection results (四层筛选结果)
    CREATE TABLE IF NOT EXISTS selection_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        select_date TEXT NOT NULL,
        etf_code TEXT NOT NULL,
        etf_name TEXT,
        layer1_passed INTEGER DEFAULT 0,    -- 基础筛选
        layer2_score REAL,                  -- 综合得分
        layer2_rank INTEGER,                -- 打分排名
        layer2_factor_details TEXT,         -- JSON: 因子明细
        layer3_theme TEXT,                  -- 题材
        layer3_theme_rank INTEGER,          -- 题材组内排名
        layer3_passed INTEGER DEFAULT 0,
        layer4_death_cross INTEGER,         -- 五重死叉 0/1
        layer4_vol_price_div INTEGER,      -- 量价背离 0/1
        layer4_adx_danger INTEGER,          -- ADX危险 0/1
        layer4_bb_risk INTEGER,             -- 布林带风险 0/1
        layer4_passed INTEGER DEFAULT 0,
        final_recommended INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        UNIQUE(select_date, etf_code)
    );

    -- 选股运行快照：保存每次 run 的完整漏斗宽度（来自全流水线，
    -- 而非仅入库的 layer3+ 子集），供「进入页面读取最新一次」与
    -- 「点击运行选股」两条路径展示完全一致的漏斗。
    CREATE TABLE IF NOT EXISTS screening_runs (
        select_date TEXT PRIMARY KEY,
        pool_total INTEGER DEFAULT 0,
        layer1 INTEGER DEFAULT 0,
        layer2 INTEGER DEFAULT 0,
        layer3 INTEGER DEFAULT 0,
        layer4 INTEGER DEFAULT 0,
        final INTEGER DEFAULT 0,
        ran_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    -- Signals (买入/卖出信号)
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT UNIQUE NOT NULL,     -- e.g. BUY-20260711-01
        signal_type TEXT NOT NULL,          -- buy / sell / empty
        etf_code TEXT,
        etf_name TEXT,
        trigger_time TEXT NOT NULL,
        trigger_details TEXT,               -- JSON: 触发条件说明
        price REAL,
        change_pct REAL,                    -- 当日涨跌幅
        suggested_amount REAL,              -- 建议买入金额
        factor_summary TEXT,                -- JSON: 因子摘要
        sell_strategy TEXT,                 -- 卖出策略名称
        sell_priority INTEGER,              -- 卖出策略优先级
        sell_action TEXT,                   -- 清仓/减仓比例
        pnl_amount REAL,                    -- 当前盈亏金额
        pnl_pct REAL,                       -- 当前盈亏百分比
        status TEXT DEFAULT 'pending',      -- pending / confirmed / skipped / executed
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    -- Positions (持仓)
    CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        etf_code TEXT NOT NULL,
        etf_name TEXT NOT NULL,
        buy_signal_id TEXT,
        buy_date TEXT NOT NULL,
        buy_price REAL NOT NULL,
        buy_amount REAL NOT NULL,           -- 买入金额
        buy_shares REAL NOT NULL,            -- 买入份额
        current_price REAL,                 -- 当前价格
        current_value REAL,                 -- 当前市值
        pnl_amount REAL DEFAULT 0,          -- 浮动盈亏金额
        pnl_pct REAL DEFAULT 0,             -- 浮动盈亏百分比
        hold_days INTEGER DEFAULT 0,         -- 持仓天数
        is_trend_stock INTEGER DEFAULT 0,    -- 是否趋势股
        status TEXT DEFAULT 'holding',       -- holding / sold
        sell_date TEXT,
        sell_price REAL,
        sell_pnl_amount REAL,
        sell_pnl_pct REAL,
        sell_strategy TEXT,                 -- 触发的卖出策略
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    -- 持仓中唯一约束：同一 ETF 只能有一条 holding 记录（防止重复开仓）。
    -- 已平仓(sold)记录可重复存在，故用部分唯一索引仅约束 status='holding'。
    CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_open_unique
        ON positions(etf_code) WHERE status='holding';

    -- Strategy parameters (策略参数配置)
    CREATE TABLE IF NOT EXISTS strategy_params (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        param_key TEXT UNIQUE NOT NULL,
        param_value TEXT NOT NULL,
        param_group TEXT NOT NULL,          -- screening / factor / buy / sell / push
        description TEXT,
        updated_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    -- Strategy param change log
    CREATE TABLE IF NOT EXISTS param_change_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        param_key TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT,
        changed_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    -- ETF pool sync log
    CREATE TABLE IF NOT EXISTS pool_sync_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sync_date TEXT NOT NULL,
        added_count INTEGER DEFAULT 0,
        removed_count INTEGER DEFAULT 0,
        total_count INTEGER DEFAULT 0,
        sync_status TEXT DEFAULT 'success',
        details TEXT,                       -- JSON: 变更明细
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    -- 待买入池（信号自动入池，人工从池子买入/移出；卖出扫描也覆盖池子）
    CREATE TABLE IF NOT EXISTS pending_buy_pool (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        etf_code TEXT NOT NULL,
        etf_name TEXT,
        entry_price REAL NOT NULL,         -- 入池点位（信号触发时现价）
        enter_time TEXT,                   -- 入池时间
        status TEXT DEFAULT 'watching',    -- watching / sold
        sell_price REAL,                  -- 被卖出扫描标记时的卖出点位
        sell_time TEXT,
        pnl_pct REAL,                    -- (sell_price/entry_price - 1) * 100，仅百分比
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime')),
        UNIQUE(etf_code)
    );

    -- System logs
    CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        log_time TEXT NOT NULL,
        level TEXT NOT NULL,                -- DEBUG / INFO / WARNING / ERROR / CRITICAL
        module TEXT,
        message TEXT NOT NULL,
        details TEXT
    );
    """)
    conn.commit()

    # ---- Schema migrations for existing databases ----
    # 待买入池增加「综合得分」字段（四层选股入池时记录，前端展示）
    _cols = [c["name"] for c in conn.execute(
        "PRAGMA table_info(pending_buy_pool)").fetchall()]
    if "score" not in _cols:
        conn.execute("ALTER TABLE pending_buy_pool ADD COLUMN score REAL")
        conn.commit()
