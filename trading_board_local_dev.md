# 交易看板（Trading Board）— 本地开发说明

> 状态：**本地开发完成，未部署生产**。后端以 `mock` 模式运行，不依赖联网。

## 新增功能
交易看板页面，集中展示 A 股主要指数及市场宽度：
- 指数卡片：上证指数、深证成指、创业板指、科创50、沪深300、上证50、北证50
- A 股配色规则：涨=红、跌=绿（与系统其它页面一致）
- 选中指数后联动展示 K 线面积图（可调 30/90/180 天）
- 市场宽度条：上涨 / 平盘 / 下跌家数 + 涨停 / 跌停
- 自动刷新（默认 30s，可暂停）+ 手动刷新，并标注数据来源（mock / akshare）

## 改动文件
### 后端
- `backend/src/infrastructure/market_indices.py`（新增）
  - 7 个指数定义 + `get_index_quotes()`（含涨跌家数） + `get_index_klines()`
  - akshare 真实数据优先；离线/本地自动降级为确定性 mock 生成器（随机种子固定，便于复现）
  - **已修复**：mock K 线日期曾生成到未来，已锚定末根 = 今天
- `backend/src/presentation/routes.py`（修改）
  - `GET /api/indices`：指数报价 + 市场宽度
  - `GET /api/indices/{code}/klines?days=`：单指数 K 线

### 前端
- `frontend/src/types/index.ts`：新增 `IndexQuote` / `MarketBreadth` / `IndexKline`
- `frontend/src/services/api.ts`：新增 `getIndices()` / `getIndexKlines()`
- `frontend/src/pages/TradingBoard.tsx`（新增）：看板主页面
- `frontend/src/App.tsx`：侧边栏新增「交易看板」入口 + 路由

## 本地运行
```bash
# 终端 1：后端（mock 模式，无需联网）
cd etf_system/backend
DATA_SOURCE=mock python -m uvicorn main:app --port 8000 --host 127.0.0.1

# 终端 2：前端
cd etf_system/frontend
npm install   # 仅首次
npm run dev   # 默认 http://localhost:3000（被占用时自动顺延，如 3001）
```
打开前端地址 → 左侧「交易看板」。

## 验证结果（本次）
- 前端 `npm run build`：✅ 通过（无 TS/JSX 错误）
- `/api/indices`：HTTP 200，返回 7 指数 + 市场宽度
- `/api/indices/000688.SH/klines?days=20`：HTTP 200，20 根 K 线，日期区间正确（末根 = 2026-07-16）
- vite dev + `/api` 代理：✅ 3000/3001 均代理到 8000 并返回 200

## 接入真实数据
部署/联网时将后端环境变量 `DATA_SOURCE` 改为 `akshare`（或移除此变量）即可走 akshare 真实行情；
`market_indices.py` 已内置新浪指数接口调用，无需改动前端。
