#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一键初始化 K 线历史缓存（真实 akshare 数据）。

为什么需要它
--------------
回测 / 离线分析依赖「全量历史日 K 线」。首次运行若逐只从 akshare 实时抓取，
全市场 ~1549 只会极慢且容易触发数据源限流。本脚本把历史**一次性落盘**到
``backend/data/kline_cache/<code>.json``，之后回测只读本地，零网络消耗、零限流焦虑。

克隆仓库后的典型用法（在 ``backend/`` 目录下执行）::

    python scripts/init_kline_cache.py                      # 默认：白名单 100 只，约 5 年历史
    python scripts/init_kline_cache.py --universe full      # 全市场 ~1549 只（极慢，慎用）
    python scripts/init_kline_cache.py --codes 510300.SH,159915.SZ
    python scripts/init_kline_cache.py --lookback-days 250 # 只拉近 1 年

特性
----
- 复用 ``src/backtest/data_source.ensure_history``：本地已落盘的 code 自动跳过，
  因此脚本**可断点续拉**（拉到一半中断，重跑只补缺失项）。
- 抓取经 provider 内部限频 + 熔断保护，不会把数据源打爆。
- 强制 ``DATA_SOURCE=akshare``（在任何 config 导入之前设置），避免 `.env`
  里若设为 mock 导致拉到假数据。
- 落盘位置见 ``config.settings.KLINE_CACHE_DIR``。
"""

import argparse
import os
import sys
import time

# ⚠️ 必须在 import config / settings 之前强制真实数据源，
# 否则若仓库 .env 设了 DATA_SOURCE=mock，会拉到假数据。
os.environ["DATA_SOURCE"] = "akshare"

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)  # backend/
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from config import settings  # noqa: E402  (env 已强制，安全)
from src.backtest.data_source import ensure_history  # noqa: E402


def resolve_codes(args) -> list:
    """根据参数解析要抓取的 ETF 代码列表。"""
    if args.codes:
        return [c.strip() for c in args.codes.split(",") if c.strip()]

    if args.universe == "full":
        # 全市场：直接从 akshare 拉取（需联网且较慢）
        from src.infrastructure.akshare_data_provider import get_akshare_provider
        provider = get_akshare_provider()
        return [e.code for e in provider.get_etf_pool()]

    # 默认：白名单小池（实盘选股宇宙，约 100 只）
    return list(settings.ETF_WHITELIST)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="初始化 K 线历史缓存（真实 akshare 数据）")
    parser.add_argument(
        "--universe", choices=["whitelist", "full"], default="whitelist",
        help="whitelist=白名单小池(默认,快) | full=全市场(极慢)")
    parser.add_argument(
        "--codes", default="",
        help="显式逗号分隔代码列表，如 510300.SH,159915.SZ")
    parser.add_argument(
        "--lookback-days", type=int, default=1200,
        help="回溯交易日数（默认 1200≈5 年；落盘始终存全量历史）")
    args = parser.parse_args()

    codes = resolve_codes(args)
    if not codes:
        print("[init] 错误：未解析到任何 ETF 代码（白名单为空或全市场抓取失败）。")
        sys.exit(1)

    print(f"[init] 宇宙={args.universe}  标的数={len(codes)}  "
          f"回溯={args.lookback_days} 交易日")
    print(f"[init] 缓存目录: {settings.KLINE_CACHE_DIR}")

    t0 = time.time()
    cached, failed, total = ensure_history(codes, args.lookback_days)
    dt = time.time() - t0

    print(f"[init] 完成：已就绪 {cached}/{total}，失败 {failed}，耗时 {dt:.1f}s")
    if failed:
        print(f"[init] 提示：{failed} 只抓取失败（多为限流/网络抖动），"
              "可直接重跑本脚本续拉，已成功的不重复抓取。")


if __name__ == "__main__":
    main()
