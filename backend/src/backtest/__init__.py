"""P3 回测框架。

最小可跑通骨架（Phase 1）：
- data_source : 历史 K 线读取（绕过 stale）+ 历史视图 Provider
- engine      : 撮合（手续费/滑点/T+1）+ 统计 + 可插拔 SignalSource
- api         : POST /api/backtest/run

设计原则：
- 信号源通过 SignalSource 接口插拔，默认 MomentumSignal 跑通管道；
  四层漏斗以 ScreeningSignalSource 复用（不复制逻辑），可作为 signal_source="screening" 切换。
- 回测引擎接收「全量历史 K 线 dict」，自己按 cursor_date 切片，
  因此测试可直接注入确定性 K 线，真实模式从 PersistentKlineStore 读取。
"""
