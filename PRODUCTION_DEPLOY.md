# ETF 量化跟踪交易系统 —— 远程生产服务器部署指南

> 适用场景：把本项目部署到一台远程 Linux 服务器，通过 `http://<服务器IP>:8000` 直接访问使用。
> 后端单进程同时托管前端与 API，**同源访问，无需 nginx / 反向代理 / HTTPS**。

---

## 0. 目标形态

| 项 | 说明 |
|----|------|
| 访问方式 | 浏览器打开 `http://<IP>:8000` |
| 数据来源 | 真实 `akshare` 行情（默认）；`mock` 可选 |
| 进程模型 | 单个 `uvicorn main:app` 监听 `0.0.0.0:8000` |
| 前端 | 构建后的 `frontend/dist/` 由后端在 `/` 托管，API 走相对路径 `/api/*` |
| 数据库 | `backend/data/etf.db`（SQLite，随包或首次启动初始化） |

---

## 1. 已就绪的服务器规格（请按需替换）

| 项 | 值 |
|----|----|
| 公网 IP | `139.199.81.98` |
| 登录账号 | `ubuntu` |
| 操作系统 | 腾讯云 Linux（Ubuntu 系） |
| 应用目录 | `/home/ubuntu/etf_system` |
| 依赖 venv | `/home/ubuntu/etf_venv` |
| 监听端口 | `8000` |
| Python | 服务器自带 `python3`（3.11+） |
| Node.js | **不要求**——前端 `dist` 在本地构建好随包上传 |

> ⚠️ 公网端口放行：腾讯云**安全组**必须手动放行 `TCP 8000` 入站规则（脚本无法代操作云控制台）。
> 若服务器启用了 `ufw` 且为 active，脚本会自动尝试 `ufw allow 8000`（需 sudo 免密或提供密码）。

---

## 2. 本机前置（一次性）

```bash
# 1) 安装部署脚本依赖 paramiko（仅本机需要，用于 SSH/SFTP）
pip install paramiko

# 2) 确认前端已构建（deploy 会把本地 dist/ 一起打包上传）
cd frontend && npm install && npm run build && cd ..
#    → 确认 frontend/dist/index.html 存在

# 3) 确认腾讯云安全组已放行 TCP 8000（控制台操作，非命令行）
```

---

## 3. 方式一：一键部署脚本 `deploy.py`（★ 推荐）

仓库根目录自带 `deploy.py`，逻辑如下：

1. 本机用 `tar` 打包最新代码（含已构建的 `frontend/dist`），自动排除 `node_modules/.git/__pycache__/*.log/data/kline_cache`
2. 通过 SFTP 上传 tar 包到服务器临时目录
3. 解压覆盖到 `/home/ubuntu/etf_system`
4. 在服务器建 `~/etf_venv` 并安装 `backend/requirements.txt`（走腾讯云 PyPI 镜像）
5. `pkill` 旧 `uvicorn` 进程，避免旧 `dist` 继续服务
6. 以 `DATA_SOURCE=akshare` 后台启动 `uvicorn main:app --host 0.0.0.0 --port 8000`
7. 轮询 `/api/universe` 验证服务就绪

### 执行

```bash
# 密码只从环境变量读取，绝不写入任何文件
export DEPLOY_PASS='<服务器密码>'
python deploy.py
```

> 脚本内置常量（需改动时编辑脚本顶部）：`HOST`、`PORT`、`USER`、`APP_DIR`、`PIP_MIRROR`。

### 预期输出与耗时

- 首次部署：pip 安装 + akshare 冷启动拉行情约 **5–8 分钟**，脚本自动轮询，不会因超时中断。
- 成功标志：脚本末尾打印 `http://139.199.81.98:8000`，且 `/api/universe` 返回含 `universe_size` 的 JSON。
- 重新部署：直接再跑一次即可，脚本会自动杀旧进程、覆盖解压。

---

## 4. 方式二：手动部署（git + 构建 + 启动）

适合不便用 `deploy.py`、或想完全掌控每一步的场景。

### 4.1 服务器操作

```bash
ssh ubuntu@139.199.81.98

# 首次：确保 python venv 工具可用
sudo apt-get update && sudo apt-get install -y python3-venv python3-pip

# 拉代码
git clone <你的仓库地址> etf_system && cd etf_system

# 后端依赖
cd backend
python3 -m venv ~/etf_venv
~/etf_venv/bin/pip install -r requirements.txt \
  -i https://mirrors.cloud.tencent.com/pypi/simple
cd ..

# 前端构建（首次或前端改过）
cd frontend
npm install && npm run build
cd ..

# 启动（前台，Ctrl+C 停止）
./start.sh                 # 默认真实 akshare 行情
# ./start.sh mock          # 模拟数据，先验证部署链路
```

### 4.2 后台常驻

```bash
nohup ./start.sh > run.log 2>&1 &
# 查看日志
tail -f run.log
```

### 4.3 访问

浏览器打开 **`http://139.199.81.98:8000`**

---

## 5. 回测历史缓存（可选）

`git clone` 后**不含** K 线历史（`backend/data/kline_cache/` 被 `.gitignore` 忽略）。
若要用「回测中心」做组合回测，先初始化：

```bash
ssh ubuntu@139.199.81.98
cd ~/etf_system/backend
python scripts/init_kline_cache.py        # 默认白名单 100 只，约 5 年
#   --universe full      # 全市场（量大、耗时长）
#   --lookback-days N   # 自定义回看天数
```

> 实时选股不依赖该缓存（走 akshare 按需抓取），仅回测模块需要。

---

## 6. 验证清单

```bash
# 1) 外网可访问（在本机执行）
curl -s --max-time 8 http://139.199.81.98:8000/api/universe
#    → 应返回含 "universe_size" 的 JSON

# 2) 前端页面
#    浏览器打开 http://139.199.81.98:8000 能看到交易看板

# 3) 服务器日志
ssh ubuntu@139.199.81.98
tail -f /home/ubuntu/etf_system/backend_run.log   # 一键脚本模式
# 或 tail -f /home/ubuntu/etf_system/run.log       # start.sh 后台模式
```

---

## 7. 进程管理

| 操作 | 命令 |
|------|------|
| 停止 | `pkill -f 'uvicorn main:app'` |
| 重启 | 重新跑 `deploy.py` 或 `./start.sh` |
| 后台常驻 | `nohup ./start.sh > run.log 2>&1 &` |
| 查看端口占用 | `sudo lsof -iTCP:8000 -sTCP:LISTEN` |

---

## 8. 安全提示

- 代码默认 `DEBUG=False`，但**未内置登录鉴权**，当前形态仅适合内网 / 可信网络访问。
- 若需暴露到公网，建议在前面加一层认证（SSH 隧道、VPN，或反向代理加 basic auth），避免交易/参数接口被任意调用。
- **密码与密钥不要写入仓库**；`DEPLOY_PASS` 仅作为运行时环境变量使用。
- 腾讯云安全组遵循最小开放原则，仅放行必要端口（8000）。

---

## 9. 排错

| 现象 | 排查 |
|------|------|
| 浏览器访问空白 / 404 | 确认 `frontend/dist/index.html` 存在：一键模式检查本地 `npm run build` 是否成功；手动模式检查服务器构建步骤 |
| 端口被占用 | `pkill -f 'uvicorn main:app'` 释放后再启动 |
| 真实数据无行情 | 服务器需能联网访问 akshare 数据源；或先用 `./start.sh mock` 验证部署链路 |
| pip 安装慢 / 失败 | 确认腾讯云镜像 `mirrors.cloud.tencent.com/pypi/simple` 可达；或临时换源 |
| 外网连不上 | 检查腾讯云**安全组**是否放行 `TCP 8000`；再查服务器 `ufw`/`iptables` |
| SFTP 上传失败 | 确认账号密码正确、`DEPLOY_PASS` 已 `export`、服务器 SSH(22) 可达 |

---

## 10. 目录与关键文件

```
etf_system/
├── deploy.py                 # 一键部署脚本（paramiko，密码从 DEPLOY_PASS 读取）
├── start.sh                 # 服务器启动脚本（构建前端 + 单进程 uvicorn）
├── start.bat                # Windows 启动脚本
├── 远程部署说明.md           # 部署原理与配置说明
├── ONBOARDING.md            # 新接手者快速上手（架构/本地跑/测试）
├── backend/
│   ├── main.py              # FastAPI 入口，托管 frontend/dist 与 /api/*
│   ├── requirements.txt
│   ├── data/               # etf.db + kline_cache/（缓存不入库）
│   └── scripts/init_kline_cache.py   # 回测历史初始化
└── frontend/
    ├── dist/               # 构建产物（deploy 随包上传）
    └── src/...
```
