import { useState, useEffect } from 'react'
import { Play, Loader2, CheckCircle2, CalendarDays, ShoppingCart, ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../services/api'
import type { ScreeningResult, ScreeningSummary } from '../types'

export default function Screening() {
  const [results, setResults] = useState<ScreeningResult[]>([])
  const [summary, setSummary] = useState<ScreeningSummary | null>(null)
  const [recommendations, setRecommendations] = useState<ScreeningResult[]>([])
  const [isEmpty, setIsEmpty] = useState(false)
  const [emptyReason, setEmptyReason] = useState('')
  const [running, setRunning] = useState(false)
  const [expandedRow, setExpandedRow] = useState<string | null>(null)
  // 让“运行是否生效”一目了然：记录最后更新时间 + 刚跑完的高亮态
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [justRan, setJustRan] = useState(false)
  // 记录本次选股推荐入池结果
  const [poolResult, setPoolResult] = useState<{ added: number; skipped: number } | null>(null)

  const runScreening = async () => {
    setRunning(true)
    setJustRan(false)
    setPoolResult(null)
    try {
      const result = await api.runScreening()
      setResults(result.all_results)
      setSummary(result.summary)
      setRecommendations(result.recommendations)
      setIsEmpty(result.is_empty_signal)
      setEmptyReason(result.empty_reason || '')
      setPoolResult({
        added: result.pool_added ?? 0,
        skipped: result.pool_skipped ?? 0,
      })
      setLastUpdated(new Date())
      setJustRan(true) // 触发“已更新”提示 + 卡片高亮
    } catch (e) {
      console.error('Screening failed:', e)
    } finally {
      setRunning(false)
    }
  }

  // 进入页面即加载「最新一次选股」结果（与运行选股返回同结构，渲染逻辑复用）
  const loadLatest = async () => {
    try {
      const result = await api.getScreeningResults()
      setResults(result.all_results || [])
      setSummary(result.summary || null)
      setRecommendations(result.recommendations || [])
      setIsEmpty(result.is_empty_signal)
      setEmptyReason(result.empty_reason || '')
      setLastUpdated(new Date())
    } catch (e) {
      console.error('Load latest screening failed:', e)
    }
  }

  useEffect(() => { loadLatest() }, [])

  // 刚跑完的“已更新”提示 4.5s 后自动消失
  useEffect(() => {
    if (!justRan) return
    const t = setTimeout(() => setJustRan(false), 4500)
    return () => clearTimeout(t)
  }, [justRan])

  const funnel = summary?.funnel
  // 选股日期（来自后端 summary.select_date，格式 YYYY-MM-DD）
  const screenDate = summary?.select_date
  const todayStr = (() => {
    const d = new Date()
    const p = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
  })()
  const isToday = screenDate === todayStr

  return (
    <div className="p-6 space-y-4">
      {/* 头部：标题 + 运行按钮 + 日期/更新时间 */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-gray-800">四层漏斗选股</h2>
          <p className="text-sm text-gray-500 mt-1">
            基础筛选 → 多因子打分 → 题材聚类 → 深度风险过滤
          </p>
          {/* 选股日期 + 更新时间：一眼看出是不是“今天”的结果 */}
          <div className="flex items-center gap-2 mt-2 flex-wrap">
            {screenDate && (
              <span className={isToday ? 'badge-success' : 'badge-warning'}>
                <CalendarDays size={12} className="inline mr-1" />
                选股日期 {screenDate}
                {isToday ? '（今日）' : '（非今日，为最近一次有效结果）'}
              </span>
            )}
            {lastUpdated && (
              <span className="text-xs text-gray-400">
                更新于 {lastUpdated.toLocaleTimeString('zh-CN')}
              </span>
            )}
          </div>
        </div>
        <button
          onClick={runScreening}
          disabled={running}
          className="btn-primary flex items-center disabled:opacity-60 disabled:cursor-not-allowed shrink-0"
        >
          {running ? (
            <Loader2 size={16} className="animate-spin mr-1" />
          ) : (
            <Play size={16} className="inline mr-1" />
          )}
          {running ? '选股中...' : '运行选股'}
        </button>
      </div>

      {/* 运行完成后短暂出现的“已更新”确认条，消除“点了没反应”的疑惑 */}
      {justRan && (
        <div className="card border-green-200 bg-green-50 flex items-center gap-2 py-3">
          <CheckCircle2 size={18} className="text-green-600" />
          <p className="text-sm font-medium text-green-700">
            已重新运行选股，结果已更新{isToday ? '' : `（最近有效日期 ${screenDate}）`}
          </p>
        </div>
      )}

      {/* 运行中：用加载面板覆盖漏斗/推荐/结果，避免看到旧数据 */}
      {running && <ScreeningLoader />}

      {/* 非运行中：展示实际结果 */}
      {!running && (
        <>
          {/* Empty signal */}
          {isEmpty && (
            <div className="card border-red-300 bg-red-50">
              <p className="text-sm font-medium text-red-600">空仓信号：{emptyReason}</p>
            </div>
          )}

          {/* Funnel visualization */}
          {funnel && (
            <div className="card">
              <h3 className="text-sm font-semibold text-gray-700 mb-4">筛选漏斗</h3>
              <div className="flex items-center justify-between gap-2">
                <FunnelStage label="ETF池" count={funnel.pool_total} width={100} color="bg-gray-400" />
                <FunnelArrow />
                <FunnelStage label="基础筛选" count={funnel.layer1} width={85} color="bg-blue-400" />
                <FunnelArrow />
                <FunnelStage label="多因子打分" count={funnel.layer2} width={65} color="bg-cyan-400" />
                <FunnelArrow />
                <FunnelStage label="题材聚类" count={funnel.layer3} width={40} color="bg-indigo-400" />
                <FunnelArrow />
                <FunnelStage label="风险过滤" count={funnel.layer4} width={25} color="bg-purple-400" />
                <FunnelArrow />
                <FunnelStage label="最终推荐" count={funnel.final} width={15} color="bg-green-500" />
              </div>
            </div>
          )}

          {/* Recommendations */}
          {recommendations.length > 0 && (
            <div className={`card border-green-200 bg-green-50 ${justRan ? 'live-flash' : ''}`}>
              <div className="flex items-center justify-between mb-2">
                <div>
                  <h3 className="text-sm font-semibold text-green-700">今日推荐 ETF（通过四层筛选）</h3>
                  {screenDate && (
                    <p className="text-xs text-green-600/80 mt-0.5">
                      选股日：{screenDate} {isToday ? '· 今日' : '· 历史结果'}
                      {lastUpdated && ` · 更新于 ${lastUpdated.toLocaleTimeString('zh-CN')}`}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <span className={isToday ? 'badge-success' : 'badge-warning'}>
                    {isToday ? '今日选股' : `选股日 ${screenDate}`}
                  </span>
                </div>
              </div>

              {/* 入池结果提示：只有本次运行后才会出现；区分「新纳入」与「已在池中」 */}
              {justRan && poolResult && (poolResult.added > 0 || poolResult.skipped > 0) && (
                <div className={`mb-3 flex items-center justify-between rounded-lg px-3 py-2 border ${
                  poolResult.added > 0 ? 'bg-green-50 border-green-200' : 'bg-amber-50 border-amber-200'
                }`}>
                  <div className={`flex items-center gap-2 text-sm ${
                    poolResult.added > 0 ? 'text-green-800' : 'text-amber-800'
                  }`}>
                    {poolResult.added > 0 ? <CheckCircle2 size={15} /> : <ShoppingCart size={15} />}
                    <span>
                      {poolResult.added > 0 ? (
                        <>已自动纳入 <strong>{poolResult.added}</strong> 只到待买入池
                          {poolResult.skipped > 0 && `（${poolResult.skipped} 只已存在/已卖出，跳过）`}</>
                      ) : (
                        <>本次推荐的 <strong>{poolResult.skipped}</strong> 只已在待买入池中（无需重复添加）</>
                      )}
                    </span>
                  </div>
                  <Link
                    to="/pending-pool"
                    className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700 hover:underline"
                  >
                    去待买入池 <ArrowRight size={12} />
                  </Link>
                </div>
              )}

              <div className="space-y-2">
                {recommendations.map(r => (
                  <div key={r.etf_code} className="flex items-center justify-between bg-white rounded-lg p-3">
                    <div>
                      <span className="font-mono text-sm text-gray-700">{r.etf_code}</span>
                      <span className="ml-2 text-sm font-medium text-gray-800">{r.etf_name}</span>
                      <span className="ml-2 badge-success">推荐</span>
                    </div>
                    <div className="text-right">
                      <span className="text-sm text-gray-600">综合得分: {r.layer2_score.toFixed(4)}</span>
                      <span className="ml-3 text-xs text-gray-400">排名 #{r.layer2_rank}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Full results table */}
          {results.length > 0 && (
            <div className="card p-0 overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-200">
                <h3 className="text-sm font-semibold text-gray-700">全部筛选结果</h3>
              </div>
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">代码</th>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">名称</th>
                    <th className="px-3 py-2 text-center font-medium text-gray-600">L1基础</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-600">L2得分</th>
                    <th className="px-3 py-2 text-center font-medium text-gray-600">L2排名</th>
                    <th className="px-3 py-2 text-center font-medium text-gray-600">L3题材</th>
                    <th className="px-3 py-2 text-center font-medium text-gray-600">L3排名</th>
                    <th className="px-3 py-2 text-center font-medium text-gray-600">死叉</th>
                    <th className="px-3 py-2 text-center font-medium text-gray-600">量价背离</th>
                    <th className="px-3 py-2 text-center font-medium text-gray-600">ADX危险</th>
                    <th className="px-3 py-2 text-center font-medium text-gray-600">布林带</th>
                    <th className="px-3 py-2 text-center font-medium text-gray-600">L4通过</th>
                    <th className="px-3 py-2 text-center font-medium text-gray-600">推荐</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map(r => (
                    <>
                      <tr key={r.etf_code} className="border-b border-gray-50 hover:bg-gray-50 cursor-pointer"
                        onClick={() => setExpandedRow(expandedRow === r.etf_code ? null : r.etf_code)}>
                        <td className="px-3 py-2 font-mono text-gray-700">{r.etf_code}</td>
                        <td className="px-3 py-2 text-gray-700">{r.etf_name}</td>
                        <td className="px-3 py-2 text-center">{r.layer1_passed ? '✅' : '❌'}</td>
                        <td className="px-3 py-2 text-right text-gray-600">{r.layer2_score?.toFixed(4)}</td>
                        <td className="px-3 py-2 text-center text-gray-600">{r.layer2_rank}</td>
                        <td className="px-3 py-2 text-center text-gray-600">{r.layer3_theme || '-'}</td>
                        <td className="px-3 py-2 text-center text-gray-600">{r.layer3_theme_rank || '-'}</td>
                        <td className="px-3 py-2 text-center">{r.layer4_death_cross ? <span className="badge-danger">是</span> : '-'}</td>
                        <td className="px-3 py-2 text-center">{r.layer4_vol_price_div ? <span className="badge-danger">是</span> : '-'}</td>
                        <td className="px-3 py-2 text-center">{r.layer4_adx_danger ? <span className="badge-danger">是</span> : '-'}</td>
                        <td className="px-3 py-2 text-center">{r.layer4_bb_risk ? <span className="badge-danger">是</span> : '-'}</td>
                        <td className="px-3 py-2 text-center">{r.layer4_passed ? <span className="badge-success">通过</span> : <span className="badge-gray">未过</span>}</td>
                        <td className="px-3 py-2 text-center">{r.final_recommended ? <span className="badge-success">推荐</span> : '-'}</td>
                      </tr>
                      {expandedRow === r.etf_code && r.factor_scores && (
                        <tr key={r.etf_code + '-detail'}>
                          <td colSpan={13} className="px-6 py-3 bg-gray-50">
                            <div className="grid grid-cols-5 gap-3">
                              {r.factor_scores.map(f => (
                                <div key={f.factor_name} className="bg-white rounded p-3 border border-gray-100">
                                  <p className="text-xs text-gray-500">{f.factor_name}</p>
                                  <p className="text-sm font-bold text-gray-700 mt-1">Z-Score: {f.z_score.toFixed(4)}</p>
                                  <p className="text-xs text-gray-400 mt-1">原始值: {f.raw_value.toFixed(4)}</p>
                                  <p className="text-xs text-gray-400">权重: {(f.weight * 100).toFixed(0)}%</p>
                                </div>
                              ))}
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {!results.length && !isEmpty && (
            <div className="card text-center py-12">
              <p className="text-gray-400">暂无选股结果，点击“运行选股”开始四层筛选流程</p>
            </div>
          )}
        </>
      )}
    </div>
  )
}

/** 运行中的加载面板：旋转 spinner + 阶段说明 + 脉冲进度条，覆盖旧数据 */
function ScreeningLoader() {
  return (
    <div className="card flex flex-col items-center justify-center py-16 space-y-4">
      <Loader2 className="animate-spin text-blue-600" size={44} />
      <p className="text-base font-medium text-gray-700">正在运行四层选股…</p>
      <p className="text-sm text-gray-400">基础筛选 → 多因子打分 → 题材聚类 → 风险过滤，请稍候</p>
      <div className="w-72 h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className="h-full bg-blue-600 rounded-full animate-pulse" style={{ width: '60%' }} />
      </div>
    </div>
  )
}

function FunnelStage({ label, count, width, color }: { label: string; count: number; width: number; color: string }) {
  return (
    <div className="flex flex-col items-center gap-1" style={{ width: `${width}%` }}>
      <div className={`${color} h-20 rounded-t-lg rounded-b-sm w-full flex items-center justify-center`}>
        <span className="text-white font-bold text-lg">{count}</span>
      </div>
      <span className="text-xs text-gray-500">{label}</span>
    </div>
  )
}

function FunnelArrow() {
  return <span className="text-gray-300 text-xl">→</span>
}
