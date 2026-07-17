# 快速上手（给接手本项目的人 / Agent）

> 读这一篇就够了：5 分钟了解是什么、怎么跑起来、怎么部署，以及前人踩过的坑。
> 细节见 `README.md`（架构 / 策略全解）与 `远程部署说明.md`（生产部署）。

## 这是什么
A 股 ETF 量化交易系统 MVP：四层漏斗选股 + 七级卖出纪律 + 实时看板 + 历史回测。
后端 FastAPI + SQLite，前端 React + TS + Tailwind，行情接 AKShare（免费，限频）。
**单进程部署**：后端同时托管 `frontend/dist`，浏览器开 `http://<IP>:8000` 即用，无需 nginx / 反向代理。

## 技术栈
- 后端：Python 3.11+ / FastAPI / SQLAlchemy / NumPy / Pandas / AKShare
- 前端：React 18 / TypeScript / Vite / Tailwind / Recharts
- 数据：AKShare（东财 + 新浪）；`mock` 模式可完全离线跑

## 目录速览
- `backend/src/screening/` 四层选股漏斗
- `backend/src/trading/` 买卖信号 + 持仓
- `backend/src/backtest/` 历史回测框架（单标的 / 组合 + 卖出纪律）
- `backend/scripts/init_kline_cache.py` clone 后初始化历史缓存（**必做**，见坑 2）
- `backend/tests/` 114 个 pytest 用例
- `frontend/src/pages/` 10 个页面（含回测中心 Backtest.tsx）
- `start.sh` / `start.bat` 生产一键启动；`deploy.py` 远程部署

## 本地 3 步跑起来
```bash
# 1) 后端
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 2) 前端（另开终端）
cd frontend
npm install
npm run dev          # http://localhost:3000，/api 自动代理到 8000

# 3)（可选，回测需要）clone 后拉历史 K 线
cd backend
python scripts/init_kline_cache.py
```
最小验证：`http://localhost:8000/docs` 看 Swagger；`GET /api/dashboard` 应有数据。

## 一键生产启动（单端口，推荐）
```bash
./start.sh            # 真实 akshare 数据；自动 build 前端并托管于 :8000
./start.sh mock       # 模拟数据，无需联网，先验证部署链路
```
Windows：`start.bat` / `start.bat mock`。浏览器开 `http://<服务器IP>:8000`。

## 部署到远程
两种方式（`远程部署说明.md` 详述）：
- **手动**：`git clone` → `pip install -r backend/requirements.txt` → （服务器有 Node 则 `npm install && npm run build`，否则本地 build 好连同 `dist/` 传上去）→ `./start.sh` → 防火墙放行 8000。
- **脚本**：`pip install paramiko && DEPLOY_PASS='...' python deploy.py`（HOST/USER/路径在脚本顶部常量）。脚本会自动 tar 打包（含 dist）、上传、装依赖、重启 uvicorn、验证可达。

## 测试
```bash
cd backend
python -m pytest        # 114 个用例；含真实 akshare 回归（test_real_deploy_regressions）
```

## ⚠️ 前人踩过的坑（必读，能省几小时）
1. **git status 会被 `| head` 截断**：提交前务必看完整 `git status`，确认所有要提交的文件都已 `git add`。曾因截断漏掉 tests/ 与两个页面，补了一次提交。
2. **K 线缓存不在仓库**：`backend/data/kline_cache/` 被 `.gitignore` 忽略。新 clone 没有历史，**跑回测前必须 `python scripts/init_kline_cache.py`**，否则报「未找到历史 K 线缓存」。
3. **AKShare 限流**：用新浪 K 线接口（`fund_etf_hist_sina`）而非东财 hist（易 `RemoteDisconnected`）。限频 + 熔断已内置，不要高频硬刷；init 脚本可断点续拉。
4. **前端构建 / 类型检查**：优先用 `npm run build` / `npm test`（走本地二进制）。直接裸调 `tsc` / `vite` 在某些 `node` 包装下会失败，应调 `node node_modules/typescript/bin/tsc` 或 `node node_modules/vite/bin/vite.js`。
5. **CRLF 警告**：Windows 上无害，忽略。
6. **数据源切换**：`config.py` 默认 `DATA_SOURCE=akshare`、`USE_WHITELIST_POOL=True`（白名单 100 只 A 股为实盘选股宇宙）。离线开发用 `./start.sh mock` 或 `DATA_SOURCE=mock`。
7. **回测真实结论（调优方向）**：白名单近 1 年组合回测，策略 **-36.7%**（叠加纪律 **-37.7%**）vs 基准等权买入持有 **+9.7%**。差距在**买侧**（漏斗持续推弱势 ETF），不在卖侧——**下一步该调选股 / 动量阈值，别再去「修」卖出纪律**。

## 改完代码别忘了
- 跑 `python -m pytest` 确保 114 全绿。
- 前端改动后 `npm run build`（生产）或 `npm run dev` 实测。
- 推远程前 `git status` 全量核对（见坑 1）。
