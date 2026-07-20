#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""极简单节点部署：本地 tar 包 -> 远程服务器 -> 装依赖 -> 单进程 uvicorn 0.0.0.0:8000

本脚本随项目仓库提供（位于仓库根目录）。所有路径基于脚本自身位置推断，可任意目录运行。
"""
import os, sys, time, tempfile, paramiko

HOST = "139.199.81.98"
PORT = 22
USER = "ubuntu"
PASS = os.environ.get("DEPLOY_PASS")  # 密码只从环境变量取，不落盘
if not PASS:
    print("ERROR: DEPLOY_PASS env not set"); sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))   # 仓库根目录 etf_system/
TARBALL_LOCAL = os.path.join(tempfile.gettempdir(), "etf_deploy.tar.gz")  # 系统临时目录，不污染仓库
TARBALL_REMOTE = "/home/ubuntu/etf_deploy.tar.gz"
APP_DIR = "/home/ubuntu/etf_system"
PIP_MIRROR = "https://mirrors.cloud.tencent.com/pypi/simple"

def log(s): print(s, flush=True)

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PASS, timeout=20, look_for_keys=False, allow_agent=False)
    return c

def ssh_run(c, cmd, timeout=60):
    try:
        stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        return out, err
    except Exception as ex:
        # 后台命令可能不主动关闭 SSH 通道，读取会超时；忽略并继续（服务端已启动）
        try:
            out = stdout.read().decode(errors="replace")
            err = stderr.read().decode(errors="replace")
        except Exception:
            out, err = "", ""
        log("[ssh_run warn] %s (continuing)" % type(ex).__name__)
        return out, err

def sftp_upload(c, local, remote):
    sftp = c.open_sftp()
    sftp.put(local, remote)
    sftp.close()

def make_tarball():
    """本地用 tar 打包最新代码（含已 build 的 frontend/dist），排除无关目录。"""
    import subprocess
    log("[*] 本地打包最新代码（含 frontend/dist）...")
    src = SCRIPT_DIR
    cmd = [
        "tar", "czf", TARBALL_LOCAL,
        "-C", src,
        "--exclude=node_modules", "--exclude=.git", "--exclude=__pycache__",
        "--exclude=*.pyc", "--exclude=backend/data", "--exclude=*.log",
        "--exclude=*.mjs", "--exclude=IMPROVEMENT_ANALYSIS.md",
        ".",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log("[!] tar 失败: " + (r.stderr or r.stdout)); sys.exit(1)
    import os as _os
    log("[+] 打包完成: %s (%.0f KB)" % (TARBALL_LOCAL, _os.path.getsize(TARBALL_LOCAL) / 1024))

def main():
    log("[*] connecting to %s@%s:%d ..." % (USER, HOST, PORT))
    make_tarball()
    c = connect()
    log("[+] connected")

    # ---- Phase A: 探测服务器环境 ----
    log("\n[PHASE A] 服务器环境")
    out, _ = ssh_run(c, "uname -a; echo '--'; python3 --version; python3 -m pip --version; echo '--'; which node || echo NO_NODE; echo '--'; nproc; free -h | head -2; echo '--'; (sudo -n true 2>/dev/null && echo SUDO_NOPASSWD_OK || echo SUDO_NEEDS_PW)")
    log(out)

    # ---- Phase B: 上传 tar 包 ----
    log("\n[PHASE B] 上传部署包 %s -> %s" % (TARBALL_LOCAL, TARBALL_REMOTE))
    t0 = time.time()
    sftp_upload(c, TARBALL_LOCAL, TARBALL_REMOTE)
    log("[+] uploaded in %.1fs" % (time.time() - t0))

    # ---- Phase C: 解压 ----
    log("\n[PHASE C] 解压到 %s" % APP_DIR)
    # 不解压删除整个目录：保留服务器已有的 backend/data（生产 etf.db / kline 缓存等运行时数据），
    # 本地 tar 包已排除 backend/data，故只覆盖代码与前端 dist，绝不覆盖生产库。
    cmd = ("mkdir -p %s && tar xzf %s -C %s && echo EXTRACT_OK && ls %s"
           % (APP_DIR, TARBALL_REMOTE, APP_DIR, APP_DIR))
    out, err = ssh_run(c, cmd, timeout=120)
    log(out); log(err)

    # ---- Phase D: 准备 venv + 安装依赖（后台 + 轮询）----
    log("\n[PHASE D] 创建 venv 并安装依赖")
    prep = ("if [ -x ~/etf_venv/bin/pip ]; then echo VENV_EXISTS; else python3 -m venv ~/etf_venv 2>/dev/null || (sudo apt-get update -qq >/dev/null 2>&1 && sudo apt-get install -y python3-venv python3-pip >/dev/null 2>&1 && python3 -m venv ~/etf_venv); fi")
    out, _ = ssh_run(c, prep, timeout=240)
    log("[venv] " + (out.strip() or "created"))
    inst = ("cd %s/backend && nohup bash -c '~/etf_venv/bin/pip install -r requirements.txt -i %s > /home/ubuntu/pip_install.log 2>&1 && echo PIP_OK >> /home/ubuntu/pip_install.log || echo PIP_FAIL >> /home/ubuntu/pip_install.log' >/dev/null 2>&1 </dev/null &"
           % (APP_DIR, PIP_MIRROR))
    ssh_run(c, inst, timeout=20)
    ok = False
    for i in range(40):  # 最多 ~6.5 分钟
        time.sleep(10)
        out, _ = ssh_run(c, "tail -n 4 /home/ubuntu/pip_install.log 2>/dev/null; echo '---'; grep -E 'PIP_OK|PIP_FAIL' /home/ubuntu/pip_install.log 2>/dev/null || true", timeout=20)
        log("[pip poll %d] %s" % (i+1, out.strip().replace(chr(10), ' | ')))
        if "PIP_OK" in out: ok = True; break
        if "PIP_FAIL" in out:
            out2, _ = ssh_run(c, "cat /home/ubuntu/pip_install.log", timeout=20)
            log("[!] pip failed:\n" + out2); break
    if not ok:
        log("[!] 依赖安装未完成/失败，中止"); c.close(); sys.exit(1)
    log("[+] 依赖安装完成")

    # ---- Phase E: 开放端口（主机防火墙，如启用）----
    log("\n[PHASE E] 主机防火墙 8000")
    fw, _ = ssh_run(c, "sudo -n ufw status 2>/dev/null | head -1 || echo NO_UFW", timeout=20)
    log("[fw] " + fw.strip())
    if "Status: active" in fw:
        ssh_run(c, "echo '%s' | sudo -S ufw allow 8000 >/dev/null 2>&1" % PASS, timeout=20)
        log("[+] ufw allow 8000 (if sudo available)")

    # ---- Phase F: 启动应用（后台）----
    log("\n[PHASE F] 启动 uvicorn (akshare, 0.0.0.0:8000)")
    # 先杀掉占用 8000 的旧 uvicorn，避免新进程起不来、旧进程继续服务旧 dist
    ssh_run(c, "pkill -f 'uvicorn main:app' 2>/dev/null; sleep 1; true", timeout=20)
    runcmd = ("cd %s/backend && nohup env DATA_SOURCE=akshare ~/etf_venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 > %s/backend_run.log 2>&1 </dev/null &"
              % (APP_DIR, APP_DIR))
    ssh_run(c, runcmd, timeout=20)
    log("[+] launch issued, waiting for startup (akshare 拉行情约 1-2 分钟)...")

    app_ok = False
    for i in range(40):  # 最多 ~6.5 分钟
        time.sleep(10)
        out, _ = ssh_run(c, "curl -s --max-time 8 http://127.0.0.1:8000/api/universe || echo NO_API", timeout=20)
        if "universe_size" in out:
            log("[app poll %d] %s" % (i+1, out.strip().replace(chr(10), ' ')))
            app_ok = True; break
        if i % 3 == 0:
            tail, _ = ssh_run(c, "tail -n 3 %s/backend_run.log 2>/dev/null" % APP_DIR, timeout=20)
            log("[app poll %d] not ready yet | log: %s" % (i+1, tail.strip().replace(chr(10), ' | ')))
    if not app_ok:
        log("[!] 应用未在预期时间内就绪，查看日志：")
        out, _ = ssh_run(c, "tail -n 20 %s/backend_run.log" % APP_DIR, timeout=20)
        log(out); c.close(); sys.exit(1)

    # ---- Phase G: 本地 + 外网可达性 ----
    log("\n[PHASE G] 验证")
    out, _ = ssh_run(c, "echo 'GET / ->'; curl -s --max-time 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/; echo; echo 'GET /signals ->'; curl -s --max-time 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/signals; echo", timeout=20)
    log("[local] " + out.strip().replace(chr(10), ' '))

    c.close()
    log("\n[✅] 部署脚本执行完毕。外网访问请确认腾讯云安全组已放行 TCP 8000。")
    log("    浏览器打开: http://%s:8000" % HOST)

if __name__ == "__main__":
    main()
