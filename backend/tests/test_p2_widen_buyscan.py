"""方案A 回归：买入扫描宇宙由 top-N 最终推荐扩到 layer4 全量通过集。

核心断言：run_buy_scan 必须覆盖"通过层4但未进前 N"的 ETF，
证明网口已扩宽，不会再因综合排名一刀切而漏掉买点。
"""

from unittest import mock

from src.trading import scan_tasks


class _FakeRes:
    """最小化 ScreeningResult 替身，仅暴露 run_buy_scan 用到的字段。"""

    def __init__(self, code: str, final: bool = False, l4: bool = True):
        self.etf_code = code
        self.final_recommended = final
        self.layer4_passed = l4
        self.layer2_score = 50.0
        self.layer2_rank = 5
        self.layer3_theme = "测试"


class _FakeScreening:
    """注入式 screening 替身，避免真实跑四层漏斗。"""

    def __init__(self, results):
        self._res = results

    def check_market_empty_signal(self):
        return (False, "")

    def get_today_recommendations(self):
        return [r for r in self._res if r.final_recommended]

    def get_today_layer4_passed(self):
        return [r for r in self._res if r.layer4_passed]


def _fake_results(codes):
    return [
        _FakeRes(codes[0], final=True, l4=True),   # top pick
        _FakeRes(codes[1], final=False, l4=True),  # 过审但未进前 N
        _FakeRes(codes[2], final=False, l4=True),  # 过审但未进前 N
        _FakeRes("NOPE.SH", final=False, l4=False),  # 未过层4 -> 不应被扫
    ]


def test_run_buy_scan_covers_layer4_not_just_final(db, buy_engine, pos_manager, mock_provider):
    """买入扫描应覆盖全部 layer4 通过项（含非 final），而非仅 top-N。"""
    pool = mock_provider.get_etf_pool()
    codes = [pool[0].code, pool[1].code, pool[2].code]
    fake = _FakeScreening(_fake_results(codes))

    # 强制每只候选都触发买入条件 -> 用以断言全部进入信号。
    # 注意：真实 check_buy_conditions 触发时会向 _condition_hold 追加，
    # generate_buy_signal 据此生成递増的 signal_id；这里同样模拟，避免 id 撞车。
    # （patch 实例属性不会自动绑定 self，故用闭包捕获 buy_engine。）
    def _force_trigger(code):
        buy_engine._condition_hold[code] = True  # dict：模拟已记录的检查，使 signal_id 递増区分
        return (True, {"forced": True})

    with mock.patch.object(buy_engine, "check_buy_conditions", _force_trigger):
        result = scan_tasks.run_buy_scan(fake, buy_engine, pos_manager, db)

    scanned = {s["etf_code"] for s in result["signals"]}
    assert result["scanned"] == 3, f"应扫描 3 只 layer4 通过项，实际 {result['scanned']}"
    assert codes[0] in scanned                 # top pick
    assert codes[1] in scanned                 # 非 final 但 layer4 通过 -> 必须被扫
    assert codes[2] in scanned                 # 非 final 但 layer4 通过 -> 必须被扫
    assert "NOPE.SH" not in scanned            # 未过层4 -> 不扫


def test_run_buy_scan_empty_when_no_layer4(db, buy_engine, pos_manager):
    """layer4 为空时直接返回空结果，不报错。"""
    fake = _FakeScreening([])
    result = scan_tasks.run_buy_scan(fake, buy_engine, pos_manager, db)
    assert result["scanned"] == 0
    assert result["triggered"] == 0


def test_layer4_universe_wider_than_final(screening):
    """真实引擎下，layer4 通过集应 >= 最终推荐，且 final 是其子集。"""
    final = screening.get_today_recommendations()
    layer4 = screening.get_today_layer4_passed()
    final_codes = {r.etf_code for r in final}
    layer4_codes = {r.etf_code for r in layer4}
    assert len(layer4) >= len(final)
    assert final_codes <= layer4_codes
