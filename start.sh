#!/usr/bin/env bash
# =============================================================================
# ETF 量化跟踪交易系统 —— 生产一键启动 (单进程: 后端托管前端, 同端口访问)
#
# 后端用 uvicorn 启动, 同时托管前端 build 产物 (frontend/dist),
# 浏览器直接访问 http://<服务器IP>:8000 即可, 无需单独前端服务 / 反向代理。
#
# 用法:
#   ./start.sh            # 默认真实 akshare 行情数据
#   ./start.sh mock       # 使用内置 mock 数据（无需联网，演示/开发用）
#   ./start.sh akshare    # 显式使用真实 akshare 行情数据
#
# 停止: Ctrl+C (脚本会清理后端进程)
# =============================================================================
set -euo pipefail

MODE="${1:-akshare}"                 # 默认真实数据
cd "$(dirname "$0")"
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
PORT=8000
BE_LOG="$ROOT/backend.log"

echo "▶ 启动模式: $MODE  (mock=模拟数据 / akshare=真实行情)"
echo "▶ 访问地址: http://<服务器IP>:$PORT"

# ---- 端口占用检查 ----
port_in_use() {
  local p="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$p" -sTCP:LISTEN -t >/dev/null 2>&1 && return 0
  fi
  if command -v netstat >/dev/null 2>&1; then
    netstat -ano 2>/dev/null | grep -qE "[:.]$p .*LISTENING" && return 0
  fi
  return 1
}
if port_in_use "$PORT"; then echo "⚠  端口 $PORT 已被占用，请先释放后再启动。"; exit 1; fi

# ---- Python 解释器 ----
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "✗ 未找到 python3，请先安装 Python 3.11+ 并安装依赖: pip install -r backend/requirements.txt"
  exit 1
fi

# ---- 前端: 有 node 就构建, 否则复用已存在的 dist/ ----
echo "▶ 准备前端 ..."
cd "$FRONTEND"
if command -v npm >/dev/null 2>&1; then
  if [ ! -d node_modules ]; then echo "  ▶ 安装前端依赖 (npm install) ..."; npm install; fi
  echo "  ▶ 构建前端 (npm run build) ..."
  npm run build
else
  if [ ! -d dist ]; then
    echo "  ✗ 未检测到 npm 且 frontend/dist 不存在。请在本地 'npm run build' 后连同 dist/ 上传。"
    exit 1
  fi
  echo "  (未检测到 npm, 复用已有 frontend/dist)"
fi

# ---- 后端单进程 (同时托管前端) ----
echo "▶ 启动后端 (端口 $PORT) ..."
cd "$BACKEND"
DATA_SOURCE="$MODE" "$PY" -m uvicorn main:app --port "$PORT" --host 0.0.0.0 > "$BE_LOG" 2>&1 &
PID_BE=$!
echo "  后端 PID=$PID_BE  →  http://localhost:$PORT"

# ---- 清理 ----
cleanup() {
  echo ""
  echo "▶ 正在停止后端 ($PID_BE) ..."
  kill "$PID_BE" >/dev/null 2>&1 || true
  wait "$PID_BE" >/dev/null 2>&1 || true
  echo "✅ 已停止。"
}
trap cleanup INT TERM EXIT

echo ""
echo "✅ 服务已启动。浏览器打开: http://<服务器IP>:$PORT"
echo "   后端日志: $BE_LOG"
echo "   按 Ctrl+C 停止。"
echo ""
wait
