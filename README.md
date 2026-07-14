# ETF 量化跟踪交易系统

基于四层漏斗选股 + 七级优先级卖出策略的 A 股 ETF 量化交易 MVP 系统。后端 FastAPI + SQLite，前端 React + TypeScript + Tailwind，接入 AKShare 实时行情数据源。

---

## 目录

- [系统概览](#系统概览)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [快速启动](#快速启动)
- [核心架构](#核心架构)
- [四层选股引擎](#四层选股引擎)
- [买入信号引擎](#买入信号引擎)
- [七级卖出策略](#七级卖出策略)
- [数据源与保护机制](#数据源与保护机制)
- [REST API 参考](#rest-api-参考)
- [数据库设计](#数据库设计)
- [配置参数](#配置参数)
- [前端页面](#前端页面)
- [扩展方向](#扩展方向)

---

## 系统概览

本系统实现了一套完整的 ETF 量化交易流程：

```
ETF池(1500+) → 四层漏斗选股 → 每日推荐(2只) → 买入信号扫描 → 持仓管理 → 卖出策略触发
```

核心能力包括：

- **四层选股漏斗**：基础筛选 → 多因子打分 → 题材聚类 → 深度风控，从 1500+ ETF 中精选 2 只
- **三条件买入信号**：MA5 回踩 + 主力资金异动 + 量能放大，附带 10 秒防抖机制
- **七级卖出策略**：紧急熔断(P100) → 高开砸盘(P90) → 危险信号(P85) → 趋势分析(P80) → 止盈止损(P75) → 冲高回落(P70) → 强制减仓(P65)
- **AKShare 实时数据**：接入东方财富/新浪行情，配备频率限制器 + 断路器保护
- **可视化看板**：7 个功能页面覆盖选股、信号、持仓、策略、绩效全流程

---

## 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| 后端框架 | FastAPI | 0.115.0 |
| ASGI 服务 | Uvicorn | 0.30.0 |
| 数据验证 | Pydantic + pydantic-settings | 2.9.0 |
| 数值计算 | NumPy + Pandas + SciPy | 1.26 / 2.2 / 1.14 |
| 数据源 | AKShare | 最新 |
| 数据库 | SQLite (WAL 模式) | 内置 |
| 前端框架 | React + TypeScript | 18.3 / 5.5 |
| 构建工具 | Vite | 5.4 |
| UI 样式 | Tailwind CSS | 3.4 |
| 图表库 | Recharts | 2.12 |
| 路由 | react-router-dom | 6.26 |
| 图标 | lucide-react | 0.439 |

---

## 项目结构

```
etf_system/
├── backend/
│   ├── main.py                             # FastAPI 入口，CORS/路由/静态文件
│   ├── config.py                           # Pydantic Settings 全局配置
│   ├── database.py                         # SQLite 初始化（WAL/外键/超时）
│   ├── requirements.txt                    # Python 依赖
│   ├── data/etf.db                         # SQLite 数据库文件
│   ├── logs/server.log                     # 应用日志
│   └── src/
│       ├── domain/
│       │   ├── entities.py                 # 业务实体（ETF/Position/Signal等）
│       │   └── enums.py                    # 枚举类型定义
│       ├── indicators/
│       │   └── technical.py                # 技术指标计算（13种指标+风控函数）
│       ├── infrastructure/
│       │   ├── akshare_data_provider.py    # AKShare 实时数据（东财+新浪）
│       │   ├── mock_data_provider.py       # Mock 数据生成器（开发/测试用）
│       │   ├── data_provider_factory.py    # 数据源工厂（mock/akshare 切换）
│       │   ├── database_repo.py            # 数据库操作层（9张表 CRUD）
│       │   └── rate_limiter.py             # 频率限制器 + 断路器
│       ├── presentation/
│       │   └── routes.py                   # REST API 端点（20+ 接口）
│       ├── screening/
│       │   └── screening_engine.py         # 四层选股漏斗引擎
│       └── trading/
│           ├── buy_signal.py               # 三条件买入信号检测
│           ├── sell_strategies.py          # 七级优先级卖出策略
│           └── position_manager.py         # 持仓生命周期管理
└── frontend/
    ├── index.html                          # HTML 入口
    ├── package.json                        # Node.js 依赖
    ├── vite.config.ts                      # Vite 构建配置（API 代理）
    ├── tailwind.config.js                  # Tailwind 主题配置
    ├── tsconfig.json                       # TypeScript 配置
    └── src/
        ├── main.tsx                        # React 入口
        ├── App.tsx                         # 主布局 + 路由（7页面）
        ├── index.css                       # 全局样式 + Tailwind 指令
        ├── pages/
        │   ├── Dashboard.tsx               # 交易看板总览
        │   ├── ETFPool.tsx                 # ETF 池管理
        │   ├── Screening.tsx               # 四层选股可视化
        │   ├── Signals.tsx                 # 买卖信号中心
        │   ├── Positions.tsx               # 持仓管理与盈亏
        │   ├── Strategy.tsx                # 策略参数配置
        │   └── Performance.tsx             # 绩效分析与归因
        ├── services/
        │   └── api.ts                      # API 客户端封装
        └── types/
            └── index.ts                    # TypeScript 类型定义
```

---

## 快速启动

### 环境要求

- Python 3.10+
- Node.js 18+
- npm 或 pnpm

### 后端启动

```bash
cd backend

# 安装依赖（国内推荐使用清华镜像）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 安装 AKShare（真实数据源）
pip install akshare

# 启动开发服务
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 前端启动

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务（端口 3000，自动代理 /api → localhost:8000）
npm run dev
```

### 访问地址

| 地址 | 说明 |
|------|------|
| http://localhost:3000 | 前端页面 |
| http://localhost:8000/api | 后端 API |
| http://localhost:8000/docs | Swagger 文档 |

### 生产构建

```bash
# 前端构建输出到 frontend/dist/
cd frontend && npm run build

# 后端自动从 frontend/dist/ 提供静态文件
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 切换数据源

编辑 `backend/config.py` 或设置环境变量：

```bash
# 使用 AKShare 真实数据
DATA_SOURCE=akshare uvicorn main:app

# 使用 Mock 模拟数据
DATA_SOURCE=mock uvicorn main:app
```

---

## 核心架构

系统采用分层架构，通过工厂模式实现数据源解耦：

```
┌─────────────────────────────────────────────────────┐
│                   Presentation                       │
│              routes.py (FastAPI Router)               │
├────────────┬────────────┬───────────────────────────┤
│  Screening │  Trading   │    Position Management     │
│  四层选股   │  买卖信号   │     持仓生命周期           │
├────────────┴────────────┴───────────────────────────┤
│                   Domain                             │
│        entities.py / enums.py (业务实体)              │
├─────────────────────────────────────────────────────┤
│                Infrastructure                        │
│  DataProviderFactory → MockProvider / AKShareProvider │
│  DatabaseRepo (SQLite)    RateLimiter + Breaker      │
└─────────────────────────────────────────────────────┘
```

**数据提供者接口（Mock 和 AKShare 均实现）：**

- `get_etf_pool()` / `get_active_etfs()` — 获取 ETF 池
- `get_klines(code, days)` — 获取日 K 线
- `get_realtime_quote(code)` — 获取实时行情
- `update_realtime()` — 刷新行情（限频 60 秒）
- `get_hs300_klines(days)` / `get_hs300_today_change()` — 沪深 300 指数

---

## 四层选股引擎

每日从全市场 ETF 中通过四层漏斗筛选出最终推荐标的：

```
ETF 池 (~1500 只)
    │
    ▼ Layer 1: 基础筛选
  ~100 只    过滤黑名单、低流动性、小市值、新上市
    │
    ▼ Layer 2: 多因子打分
   30 只     5 因子 Z-Score 加权排名
    │
    ▼ Layer 3: 题材聚类
  ~12 只     按主题分组，每组保留 Top 2
    │
    ▼ Layer 4: 深度风控
   2~5 只    四重风险检测全部通过
    │
    ▼ 最终推荐
    2 只     每日精选标的
```

### Layer 1：基础筛选

过滤条件（全部满足才通过）：

- 状态非黑名单/排除/债券/货币/LOF
- 日均成交额 ≥ 3,000 万元
- 总市值 ≥ 80 亿元
- 上市时间 ≥ 30 天（20 个交易日）
- 白名单 ETF 无条件通过

### Layer 2：多因子打分

5 个因子 Z-Score 标准化后加权合成：

| 因子 | 权重 | 原始指标 | 说明 |
|------|------|----------|------|
| 趋势强度 | 25% | 20 日线性回归斜率 | 衡量中期趋势方向 |
| 动量得分 | 20% | 5 日收益×0.6 + 10 日收益×0.4 | 短期动能 |
| 量能指标 | 15% | 5 日均量 / 20 日均量 | 资金流入趋势 |
| 波动率 | 10% | 20 日年化波动率（取反） | 低波动优先 |
| 技术指标 | 30% | 8 项子指标均值 | RSI/MACD/KDJ/OBV/BB/BIAS/VR |

技术子指标评分规则：RSI 超卖(<30)得+1、超买(>70)得-1；MACD 金叉+1、死叉-0.5；KDJ-J 超卖(<20)+1、超买(>80)-1；OBV 向上+1、向下-1；布林带靠近下轨+0.5、上轨-0.5；BIAS 为负看多、为正看空；VR>1.2 资金流入+1、<0.8 流出-1。

### Layer 3：题材聚类

按 15 个主题（芯片半导体、新能源、医药、消费、金融、科技、军工、光伏、创业板、沪深300、跨境、有色、房地产、农业等）对 ETF 分组，每个主题保留当日涨幅排名前 2 只，避免同题材过度集中。

### Layer 4：深度风控

四项风险检测全部通过才标记为推荐：

1. **五重死叉**：MA5 < MA10 < MA20 < MA30 < MA60
2. **量价背离**：价格处于高位但成交量持续萎缩
3. **ADX 危险**：ADX < 25，趋势动能不足
4. **布林突破**：价格突破上轨，存在回调风险

### 空仓信号

若沪深 300 当日跌幅 < -2%，系统触发空仓信号（"建议观望"），跳过选股。

---

## 买入信号引擎

对每日推荐的 ETF 进行实时扫描，当三个条件同时满足时触发买入信号：

### 三条件

| 条件 | 公式 | 参数 |
|------|------|------|
| MA5 回踩 | \|现价 - MA5\| / MA5 ≤ 容忍度 | 1.5% |
| 主力资金异动 | 预估全日成交量 ≥ 异动倍数 × 5日均量 × 0.3 | 2.0 倍 |
| 量能放大 | 当日成交量 / 5日均量 ≥ 倍数 | 1.5 倍 |

### 防抖机制

信号条件需持续满足 ≥ 10 秒才正式触发，防止瞬时波动造成假信号。

### 冷却期

卖出后 5 个交易日内不重复买入同一 ETF，避免来回震荡。

### 建议买入金额

```
建议金额 = 总资金 × 单只仓位上限 = 100,000 × 30% = 30,000 元
```

---

## 七级卖出策略

按优先级从高到低依次检查，触发最高优先级的策略即执行：

### P100 紧急熔断

- **触发**：浮亏 ≤ -5%
- **动作**：清仓
- **目的**：立即止损，保护本金

### P90 高开砸盘

- **触发**：09:30-10:30 期间，开盘涨幅 > 2%，从开盘价回落 > 0.8%，且非趋势股
- **动作**：清仓
- **目的**：识别主力借高开出货

### P85 危险信号

- **触发**：出现死叉、量价背离、ADX 危险中的任意组合
- **动作**：≥ 2 个信号清仓，1 个信号减仓 50%
- **目的**：多重利空确认时果断离场

### P80 趋势分析

- **触发**：趋势股连续 3 天收盘价跌破 MA20
- **动作**：清仓
- **说明**：仅对趋势股生效，非趋势股不触发此策略

### P75 止盈止损

**阶梯止盈：**

| 浮盈幅度 | 动作 |
|----------|------|
| ≥ 30% | 卖出 1/3 |
| ≥ 40% | 再卖出剩余的 1/2 |
| ≥ 50% | 全部清仓 |

**动态止损：**

| 持仓天数 | 止损线 | 说明 |
|----------|--------|------|
| < 5 天 | -7.2% | 短线放宽，给波动空间 |
| 5-10 天 | -6.0% | 基础止损 |
| > 10 天 | -5.4% | 长线收紧，保护利润 |

### P70 冲高回落

- **触发**：盘中涨幅曾达 2.6% 以上后回落
- **动作**：

| 回落幅度 | 动作 |
|----------|------|
| ≥ 0.6% | 卖出 1/3 |
| ≥ 1.0% | 卖出 1/2 |
| ≥ 1.5% | 清仓 |

### P65 强制减仓

- **触发**：涨幅 > 3.5% 且 5 分钟内未创新高（09:25-09:40 除外）
- **动作**：减仓 50%
- **目的**：强势行情中锁定部分利润

---

## 数据源与保护机制

### AKShare 数据源映射

| API 函数 | 数据源 | 用途 | 备注 |
|----------|--------|------|------|
| `fund_etf_spot_em()` | 东方财富 | ETF 池 + 实时行情 | 15 页分页拉取，~25 秒 |
| `fund_etf_fund_daily_em()` | 东方财富 | ETF 类型分类 | 用于排除债券/货币/LOF |
| `fund_etf_hist_sina()` | 新浪 | 日 K 线 OHLCV | 逐只拉取，按需缓存 |
| `stock_zh_index_daily()` | 新浪 | 沪深 300 指数 K 线 | 一次性加载 |

> 东方财富的 `fund_etf_hist_em` 和 `index_zh_a_hist` 接口容易被限流（`RemoteDisconnected`），故优先使用新浪接口获取 K 线和指数数据。

### 单位换算

| 字段 | 原始单位 | 系统单位 | 换算 |
|------|----------|----------|------|
| 成交量 | 股 | 手 | ÷ 100 |
| 成交额 | 元 | 万元 | ÷ 10,000 |
| 总市值 | 元 | 亿元 | ÷ 100,000,000 |

### 代码格式转换

| 格式 | 示例 | 规则 |
|------|------|------|
| 系统内部 | 510300.SH | 5/6 开头 = SH，其他 = SZ |
| AKShare sina | sh510300 | 小写交易所前缀 |
| AKShare spot | 510300 | 6 位纯数字 |

### 频率限制器（RateLimiter）

线程安全的最小间隔控制器，按数据源独立限频：

| 数据源 | 最小间隔 | 说明 |
|--------|----------|------|
| eastmoney_spot | 60 秒 | 15 页分页，请求量大 |
| eastmoney_daily | 30 秒 | 分类数据，较轻 |
| sina_kline | 1 秒 | 逐只 K 线，批量拉取 |
| sina_index | 60 秒 | 指数数据 |
| update_realtime | 60 秒 | 行情刷新全局下限 |

### 断路器（CircuitBreaker）

三态自动降级保护：

```
CLOSED（正常）──连续失败达阈值──→ OPEN（熔断，快速失败）
                                     │
                                冷却期过后
                                     │
                                     ▼
                               HALF_OPEN（试探恢复）
                               │            │
                          请求成功       请求失败
                               │            │
                               ▼            ▼
                            CLOSED        OPEN
```

| 断路器 | 数据源 | 失败阈值 | 冷却期 |
|--------|--------|----------|--------|
| breaker_spot_em | 东财实时 | 3 次 | 300 秒 |
| breaker_daily_em | 东财分类 | 3 次 | 300 秒 |
| breaker_hist_sina | 新浪 K 线 | 5 次 | 120 秒 |
| breaker_index_sina | 新浪指数 | 5 次 | 120 秒 |

### 缓存策略

- **ETF 池**：启动时加载一次，手动同步时刷新
- **K 线数据**：首次请求时拉取并缓存，后续命中缓存（第二次选股零网络请求，~3 秒完成）
- **实时行情**：启动时加载，`update_realtime()` 刷新（最低间隔 60 秒）
- **HS300 指数**：启动时加载一次

---

## REST API 参考

### 看板

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/dashboard` | 组合概览、信号、大盘状态、绩效 |

### ETF 池

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/etf-pool` | 分页列表（支持 status/etf_type 过滤） |
| GET | `/api/etf-pool/{code}` | 单只详情 + K 线 + 实时行情 |
| PUT | `/api/etf-pool/{code}/status` | 更新状态（blacklist/whitelist） |
| POST | `/api/etf-pool/sync` | 手动同步 ETF 池 |
| GET | `/api/etf-pool/sync-logs` | 同步历史 |

### 选股

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/screening/run` | 执行四层选股（耗时 ~100 秒首次/~3 秒缓存） |
| GET | `/api/screening/results` | 查询某日选股结果 |

### 信号

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/signals` | 信号列表（支持 type/status 过滤） |
| POST | `/api/signals/buy/scan` | 扫描推荐 ETF 的买入信号 |
| POST | `/api/signals/sell/scan` | 扫描所有持仓的卖出信号 |
| POST | `/api/signals/{signal_id}/confirm` | 确认买入并建仓 |
| POST | `/api/signals/{signal_id}/skip` | 跳过信号 |

### 持仓

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/positions` | 持仓列表（支持 status 过滤） |
| GET | `/api/positions/summary` | 组合汇总 |
| POST | `/api/positions/{position_id}/sell` | 手动平仓 |

### 策略参数

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/strategy/params` | 获取全部参数（按组分类） |
| PUT | `/api/strategy/params` | 修改参数（记录变更日志） |
| POST | `/api/strategy/preset` | 应用预设（conservative/standard/aggressive） |
| POST | `/api/strategy/reset` | 恢复默认值（26 项参数） |

### 绩效

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/performance` | 胜率、月度统计、策略分布、交易明细 |

### 实时行情

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/realtime` | 获取实时行情（支持 codes 过滤） |
| POST | `/api/realtime/tick` | 刷新行情（限频 60 秒） |

### 健康监控

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health/data-source` | 数据源状态、断路器、缓存统计 |
| POST | `/api/health/circuit-breaker/reset` | 手动重置所有断路器 |

---

## 数据库设计

SQLite 数据库（WAL 模式），位于 `backend/data/etf.db`，共 10 张表：

### 表结构概览

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `etf_pool` | ETF 元数据 | code(UK), name, exchange, etf_type, theme, avg_amount_20d, total_market_cap, status |
| `daily_kline` | 日 K 线 | (etf_code, trade_date) UK, OHLCV, amount |
| `index_daily` | 指数 K 线 | (index_code, trade_date) UK, OHLCV |
| `selection_results` | 选股结果 | (select_date, etf_code) UK, layer1~4 各字段, factor_details(JSON) |
| `signals` | 买卖信号 | signal_id(UK), signal_type, trigger_details(JSON), status |
| `positions` | 持仓记录 | etf_code, buy/sell 价格/日期/金额, pnl, is_trend_stock, status |
| `strategy_params` | 策略参数 | param_key(UK), param_value, param_group |
| `param_change_log` | 参数变更日志 | param_key, old_value, new_value, changed_at |
| `pool_sync_log` | 同步日志 | sync_date, added/removed/total_count, sync_status |
| `system_logs` | 系统日志 | log_time, level, module, message |

### 数据库连接配置

```python
journal_mode = WAL          # 支持并发读写
synchronous = NORMAL        # 平衡安全与性能
busy_timeout = 5000         # 锁等待 5 秒
foreign_keys = ON           # 启用外键约束
row_factory = sqlite3.Row   # 字典式访问
```

---

## 配置参数

所有参数定义在 `backend/config.py`，支持环境变量和 `.env` 文件覆盖。

### 资金与仓位

| 参数 | 默认值 | 说明 |
|------|--------|------|
| TOTAL_CAPITAL | 100,000 | 总资金（元） |
| SINGLE_POSITION_LIMIT | 0.30 | 单只 ETF 仓位上限 30% |
| TOTAL_POSITION_LIMIT | 0.80 | 总仓位上限 80% |
| DAILY_SELECT_COUNT | 2 | 每日推荐数量 |

### 选股参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| MOMENTUM_PERIOD | 20 | 动量计算周期（天） |
| LIQUIDITY_THRESHOLD | 3,000 | 日均成交额门槛（万元） |
| MARKET_CAP_THRESHOLD | 80 | 总市值门槛（亿元） |
| MARKET_DROP_THRESHOLD | -2.0 | 沪深 300 空仓信号阈值 |
| SELL_COOLDOWN_DAYS | 5 | 卖出冷却期（交易日） |

### 因子权重

| 参数 | 默认值 | 说明 |
|------|--------|------|
| WEIGHT_TREND | 0.25 | 趋势强度权重 |
| WEIGHT_MOMENTUM | 0.20 | 动量得分权重 |
| WEIGHT_VOLUME | 0.15 | 量能指标权重 |
| WEIGHT_VOLATILITY | 0.10 | 波动率权重 |
| WEIGHT_TECHNICAL | 0.30 | 技术指标权重 |

> 五项权重之和必须等于 1.0。前端有校验提示。

### 买入参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| BUY_MA5_TOLERANCE | 0.015 | MA5 回踩容忍度 1.5% |
| BUY_VOLUME_SURGE_MULT | 2.0 | 主力资金异动倍数 |
| BUY_VOLUME_RATIO | 1.5 | 当日量/5日均量倍数 |
| BUY_SIGNAL_HOLD_SECONDS | 10 | 信号持续满足秒数 |

### 卖出参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| EMERGENCY_LOSS_THRESHOLD | -5.0 | 紧急熔断浮亏阈值 |
| HIGH_OPEN_THRESHOLD | 2.0 | 高开幅度阈值 |
| HIGH_OPEN_DROP_THRESHOLD | -0.8 | 高开后回调阈值 |
| TREND_BREAK_MA_DAYS | 3 | 趋势破位未收回天数 |
| TAKE_PROFIT_THRESHOLD | 30.0 | 止盈阈值 |
| STOP_LOSS_BASE | -6.0 | 基础止损 |
| STOP_LOSS_RELAXED | -7.2 | 持仓<5天放宽止损 |
| STOP_LOSS_TIGHTENED | -5.4 | 持仓>10天收紧止损 |
| PEAK_REVERSAL_RISE | 2.6 | 冲高回落日涨幅阈值 |
| MANDATORY_RISE | 3.5 | 强制减仓涨幅阈值 |

### 预设模板

| 预设 | 趋势 | 动量 | 量能 | 波动 | 技术 |
|------|------|------|------|------|------|
| 保守型 | 30% | 10% | 10% | 20% | 30% |
| 标准型 | 25% | 20% | 15% | 10% | 30% |
| 激进型 | 30% | 30% | 10% | 5% | 25% |

---

## 前端页面

系统包含 7 个功能页面，左侧边栏导航：

| 页面 | 路径 | 功能 |
|------|------|------|
| **看板** | `/` | 大盘状态（HS300涨跌）、总资产、浮盈亏、持仓概览、最近信号、快捷操作 |
| **ETF 池** | `/etf-pool` | 分页浏览 1500+ ETF，状态/类型过滤，黑名单管理，手动同步 |
| **四层选股** | `/screening` | 漏斗可视化（6 阶段）、推荐结果、因子评分展开详情 |
| **信号中心** | `/signals` | 买卖信号卡片、触发详情、确认/跳过操作 |
| **持仓看板** | `/positions` | 持仓/已平仓切换、实时盈亏、趋势股标识、手动卖出 |
| **策略设置** | `/strategy` | 三套预设、因子权重校验、26 项参数分组编辑 |
| **绩效看板** | `/performance` | 胜率/盈亏比、累计盈亏曲线、月度柱状图、策略分布饼图、交易明细 |

---

## 扩展方向

| 方向 | 当前状态 | 可扩展内容 |
|------|----------|------------|
| 数据源 | Mock + AKShare 双源 | 接入 Tushare/Wind/Bloomberg，WebSocket 实时推送 |
| 选股模型 | 规则引擎 + 固定权重 | 机器学习因子模型，动态权重，情绪分析 |
| 交易执行 | 手动确认 | 对接券商 API 自动下单，模拟盘模式 |
| 回测框架 | 无 | 历史数据回测，参数寻优，蒙特卡洛模拟 |
| 风控指标 | 基础盈亏统计 | Sharpe/Sortino/最大回撤，基准对比，因子归因 |
| 用户系统 | 单用户无鉴权 | 多用户、角色权限、操作审计 |
| 通知推送 | 无 | 企业微信/钉钉/Telegram 信号推送 |
| 移动端 | 仅 Web | React Native 移动 App |
