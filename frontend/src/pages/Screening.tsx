import { useState, useEffect } from 'react'
import { Play, ChevronDown, ChevronUp } from 'lucide-react'
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

  const runScreening = async () => {
    setRunning(true)
    try {
      const result = await api.runScreening()
      setResults(result.all_results)
      setSummary(result.summary)
      setRecommendations(result.recommendations)
      setIsEmpty(result.is_empty_signal)
      setEmptyReason(result.empty_reason || '')
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
    } catch (e) {
      console.error('Load latest screening failed:', e)
    }
  }

  useEffect(() => { loadLatest() }, [])

  const funnel = summary?.funnel

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-800">四层漏斗选股</h2>
          <p className="text-sm text-gray-500 mt-1">
            基础筛选 → 多因子打分 → 题材聚类 → 深度风险过滤
          </p>
        </div>
        <button onClick={runScreening} disabled={running} className="btn-primary">
          <Play size={16} className="inline mr-1" />
          {running ? '选股中...' : '运行选股'}
        </button>
      </div>

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
            <ArrowRight />
            <FunnelStage label="基础筛选" count={funnel.layer1} width={85} color="bg-blue-400" />
            <ArrowRight />
            <FunnelStage label="多因子打分" count={funnel.layer2} width={65} color="bg-cyan-400" />
            <ArrowRight />
            <FunnelStage label="题材聚类" count={funnel.layer3} width={40} color="bg-indigo-400" />
            <ArrowRight />
            <FunnelStage label="风险过滤" count={funnel.layer4} width={25} color="bg-purple-400" />
            <ArrowRight />
            <FunnelStage label="最终推荐" count={funnel.final} width={15} color="bg-green-500" />
          </div>
        </div>
      )}

      {/* Recommendations */}
      {recommendations.length > 0 && (
        <div className="card border-green-200 bg-green-50">
          <h3 className="text-sm font-semibold text-green-700 mb-3">今日推荐 ETF（通过四层筛选）</h3>
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

      {!results.length && !running && (
        <div className="card text-center py-12">
          <p className="text-gray-400">暂无选股结果，点击"运行选股"开始四层筛选流程</p>
        </div>
      )}
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

function ArrowRight() {
  return <span className="text-gray-300 text-xl">→</span>
}
