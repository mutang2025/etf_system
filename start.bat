@echo off
chcp 65001 >nul
REM ============================================================================
REM  ETF 量化跟踪交易系统 —— 生产一键启动 (单进程: 后端托管前端, 同端口访问)
REM
REM  后端用 uvicorn 启动, 同时托管前端 build 产物 (frontend/dist),
REM  浏览器直接访问 http://<服务器IP>:8000 即可, 无需单独前端服务 / 反向代理。
REM
REM  用法:
REM    start.bat          默认使用真实 akshare 行情数据
REM    start.bat mock     使用内置 mock 数据（无需联网，演示/开发用）
REM    start.bat akshare  显式使用真实 akshare 行情数据
REM
REM  停止: 关闭弹出的 "ETF-Backend" 命令行窗口即可。
REM ============================================================================
setlocal
set MODE=%1
if "%MODE%"=="" set MODE=akshare

cd /d %~dp0
set ROOT=%CD%
set BACKEND=%ROOT%\backend
set FRONTEND=%ROOT%\frontend
set PORT=8000
set BE_LOG=%ROOT%\backend.log

echo ▶ 启动模式: %MODE%  (mock=模拟数据 / akshare=真实行情)
echo ▶ 访问地址: http://^<服务器IP^>:%PORT%

REM ---- 端口占用检查 ----
netstat -ano 2>nul | findstr "0.0.0.0:%PORT%" | findstr "LISTENING" >nul && (
  echo ⚠ 端口 %PORT% 已被占用，请先释放后再启动。
  pause
  exit /b 1
)

REM ---- Python 检查 ----
where python >nul 2>&1 || (echo ✗ 未找到 python，请先安装并 pip install -r backend/requirements.txt & pause & exit /b 1)

REM ---- 前端: 有 node 就构建, 否则复用已存在的 dist/ ----
echo ▶ 准备前端 ...
cd /d %FRONTEND%
where npm >nul 2>&1
if errorlevel 1 (
  if not exist dist (
    echo ✗ 未检测到 npm 且 frontend/dist 不存在。请在本地 npm run build 后连同 dist 上传。
    pause
    exit /b 1
  )
  echo   (未检测到 npm, 复用已有 frontend/dist)
) else (
  if not exist node_modules call npm install
  call npm run build
)

REM ---- 后端单进程 (同时托管前端) ----
echo ▶ 启动后端 (端口 %PORT%) ...
cd /d %BACKEND%
set DATA_SOURCE=%MODE%
start "ETF-Backend" cmd /k "echo 后端日志: %BE_LOG% & python -m uvicorn main:app --port %PORT% --host 0.0.0.0 >> %BE_LOG% 2>&1"

echo.
echo ✅ 已启动。浏览器打开: http://^<服务器IP^>:%PORT%
echo    后端日志见 "ETF-Backend" 窗口 (或 %BE_LOG%)
echo    关闭该窗口即停止服务。
echo.
pause
endlocal
