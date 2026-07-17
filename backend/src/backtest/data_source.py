"""回测数据层：历史 K 线读取 + 历史视图 Provider。

回测与盘中实时扫描的关键差异：
- 实时扫描永远看「截至今天」的数据；
- 回测要在「历史上的每一天」都重放一遍，因此需要按 cursor_date 把 K 线切成
  「截至该日」的窗口，再喂给信号源（动量指标 / 四层漏斗）。

本模块提供：
1. load_klines_from_store(codes) —— 从 PersistentKlineStore 读**全量**历史
   （绕过 stale 检查，回测允许使用早于今天的数据）。
2. HistoricalViewProvider —— 包装全量 K 线，按 cursor_date 提供 get_klines 切片，
   使 ScreeningEngine 能在历史上运行，从而复用四层漏斗作为信号源。
"""

import json
import os
from typing import Optional

from config import settings
from src.domain.entities import DailyKline
from src.infrastructure.kline_cache import PersistentKlineStore


def load_klines_from_store(codes: list[str], cache_dir: Optional[str] = None) -> dict:
    """从本地落盘缓存读取给定代码的全量历史 K 线。

    回测假定数据已落盘（首次抓取见 akshare_data_provider / 下方 fetch 说明）。
    直接读 JSON 文件、绕过 PersistentKlineStore 的 stale 判定，
    因为回测需要的是「早于今天」的历史，而非必须最新交易日。

    Returns: {code: list[DailyKline]}，缺失/损坏的 code 自动跳过。
    """
    store = PersistentKlineStore(cache_dir)
    out: dict = {}
    for code in codes:
        kl = _read_full(store, code)
        if kl:
            out[code] = kl
    return out


def _read_full(store: PersistentKlineStore, code: str) -> Optional[list]:
    """绕过 stale 检查，直接读某个 code 的全部历史 K 线。"""
    path = PersistentKlineStore._file_path(store.cache_dir, code)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return [DailyKline(**d) for d in raw]
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return None


class HistoricalViewProvider:
    """把「全量历史 K 线」包装成「截至 cursor_date 的视图」。

    仅实现 ScreeningEngine 实际需要的方法：
    - get_klines(code, days) -> 截至 cursor 的最近 days 天
    - get_etf_pool()            -> 回测宇宙

    其余方法透传 base（若提供），保证 ScreeningEngine 内部任何未预期调用不崩。
    这样回测每天 new 一个 view（cursor=当日）跑 run_full_screening，
    四层漏斗就在该历史截面上运行——零复制、随漏斗逻辑自动演进。
    """

    def __init__(self, full_klines_by_code: dict, cursor_date: str,
                 pool: list, base=None):
        self._full = full_klines_by_code
        self._cursor = cursor_date
        self._pool = pool
        self._base = base

    def get_klines(self, code: str, days: int = 120) -> list:
        kl = self._full.get(code, [])
        upto = [k for k in kl if k.trade_date <= self._cursor]
        return upto[-days:] if days < len(upto) else upto

    def get_etf_pool(self) -> list:
        return self._pool

    def __getattr__(self, name):
        # 仅当显式属性缺失时才透传 base（__init__ 已设置的属性不会走到这）
        if name == "_base":
            raise AttributeError(name)
        base = self.__dict__.get("_base")
        if base is not None:
            return getattr(base, name)
        raise AttributeError(name)


def ensure_history(codes: list[str], lookback_days: int = 1200,
                   provider=None) -> tuple[int, int, int]:
    """抓取并落盘给定代码的全量历史 K 线（供全市场回测使用）。

    策略：
    1. 本地落盘缓存已存在的 code 直接计为 cached，跳过网络；
    2. 缺失的调 provider.get_klines(code, lookback_days) —— 该方法内部已实现
       限频（rate_limiter）+ 熔断（circuit_breaker）+ 落盘持久化，
       故这里无需自行处理反爬，只负责「遍历 + 计数」。
    3. 拉取失败（熔断开启 / 网络异常）计入 failed，不阻塞其余 code。

    返回 (cached, failed, total)。total = len(codes)（含已缓存）。

    这是「全市场真实回测」数据抓取第一层：首次把白名单/全池历史
    落本地 JSON，之后回测只读本地，零网络消耗、零限流焦虑。
    """
    from src.infrastructure.data_provider_factory import get_data_provider

    prov = provider or get_data_provider()
    cached = 0
    failed = 0
    total = len(codes)
    for code in codes:
        # 1) 已落盘则跳过
        if load_klines_from_store([code]):
            cached += 1
            continue
        # 2) 缺失则现拉（provider 内部限频 + 熔断 + 落盘）
        try:
            kl = prov.get_klines(code, lookback_days)
            if kl:
                cached += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    return cached, failed, total
