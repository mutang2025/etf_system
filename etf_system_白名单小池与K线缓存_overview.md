# ETF 系统 · 真实数据性能优化（白名单小池 + K 线落盘缓存）

> 落地于 2026-07-15。针对「真实 akshare 数据全市场扫描极慢」这一瓶颈。

## 瓶颈根因
原 `run_full_screening` 的 Layer 2 对**池中每一只 ETF 逐只拉取日 K 线**。真实模式下全市场约 **1544 只** ETF，每只一次 `fund_etf_hist_sina` 网络请求（且受 1s 限速 + 熔断保护），一次完整选股要几分钟，还极易把数据源限流/熔断打满。守护进程每 10s 一轮时情况更糟（虽有「当日推荐缓存」只跑一次/天，但**冷启动**每次都重拉 1544 只）。

## 两项优化

### 1. ETF 白名单小池（Whitelist Small Pool）
- `config.py`：新增 `USE_WHITELIST_POOL=True` 与 `ETF_WHITELIST`（精选 **36** 只高流动性宽基/行业/跨境/商品 ETF，可编辑）。
- `screening_engine.py`：新增 `get_scan_universe()`，仅当 `DATA_SOURCE=="akshare"` 且启用白名单时，把扫描池收敛为白名单与全市场的交集；为空则回退全池（防误配）。`run_full_screening` 改用它作为 Layer 0 输入。
- `akshare_data_provider.py`：`_load_etf_pool` 中将白名单代码的 `status` 置为 `whitelist`，使 Layer 1 基础过滤**直通**（不被流动性/市值门槛误杀）。
- **Mock 模式不受影响**：白名单逻辑仅在 `akshare` 模式生效，mock 测试/演示仍走全池。

### 2. K 线落盘缓存（Persistent K-line Cache）
- 新增 `src/infrastructure/kline_cache.py`：`PersistentKlineStore`，按代码以 JSON 落盘到 `backend/data/kline_cache/`，含 `_index.json` 记录每个代码的最新交易日。
- 三级缓存层级（`akshare_data_provider.get_klines`）：① 进程内 dict → ② 落盘 JSON（**重启持久**）→ ③ 网络拉取（成功后写回两层）。
- **新鲜度**：日 K 线最多每日变一次。缓存被视为新鲜当且仅当其最新交易日 `>=`「最近交易日」（周末回退到上周五）；过期则自动重拉，实现零人工干预的每日刷新。
- `get_health_status` 增加 `kline_persistent_cached` 计数。

### 3. 可观测性
- `routes.py` 新增 `GET /api/universe`：返回 `data_source` / `use_whitelist` / `whitelist_size` / `universe_size` / 小池明细 / `kline_persistent_cached`。
- `realtime_scanner.get_status` 增加 `universe_size` 与 `use_whitelist`。
- `.gitignore` 增加 `backend/data/kline_cache/`（派生缓存不入库）。

## 验证结果（真实 akshare，端口 8077）
- `GET /api/universe` → `use_whitelist=true, whitelist_size=36, universe_size=35`（36 只中 35 只命中实时池，1 只未匹配被优雅丢弃），全部 `status=whitelist`。
- `POST /api/scanner/force-scan` 触发一次完整扫描：
  - 日志：`Whitelist pool: 35 ETFs (from 1544 total)` → `Layer 0: 35` → `Layer 1: 35 passed`。
  - `sina_kline` 熔断器：`total_calls=35, total_failures=0`，**而非 1544**。
  - `backend/data/kline_cache/` 生成 35 个 `{code}.json` + `_index.json`；`kline_persistent_cached=35`。

## 性能收益
| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 单次选股 K 线网络请求 | ~1544 | **35**（↓约 44×） |
| 冷启动首扫 | 重拉全市场 | 仅拉白名单（且落盘缓存二次启动≈0 网络） |
| 守护进程每轮 | 受当日推荐缓存保护，但首扫仍 1544 | 首扫 35 + 落盘缓存 |

## 测试
- 新增 `backend/tests/test_whitelist_kline_cache.py`：`get_scan_universe` 在 akshare/mock 两种模式行为、空白名单回退；`PersistentKlineStore` 往返一致、新鲜度判定（跨交易日失效）、空输入安全、周末回退周五。
- 全量 pytest：32 passed。

## 可调整项
- 编辑 `config.py` 的 `ETF_WHITELIST` 即可改小池标的（如扩到 50~80 只仍远小于全市场）。
- 关闭优化：`USE_WHITELIST_POOL=False` 即回退全市场扫描（白名单仍作 Layer1 直通标记，无副作用）。
- 缓存目录：`config.py` 的 `KLINE_CACHE_DIR`，删除该目录即可强制全量重拉。
