import { useState } from 'react'
import { LineChart as LineIcon, Play, Download, AlertTriangle, TrendingUp, Percent, Activity } from 'lucide-react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { api } from '../services/api'

type Mode = 'single' | 'portfolio'
type Universe = 'whitelist' | 'full'

function todayISO() { return new Date().toISOString().slice(0, 10) }
function yearsAgoISO(y: number) {
  const d = new Date()
  d.setFullYear(d.getFullYear() - y)
  return d.toISOString().slice(0, 10)
}

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#6366f1']

export default function Backtest() {
  const [mode, setMode] = useState<Mode>('portfolio')
  const [universe, setUniverse] = useState<Universe>('whitelist')
  const [signalSource, setSignalSource] = useState<'momentum' | 'screening'>('momentum')
  const [codes, setCodes] = useState('510300.SH')
  const [start, setStart] = useState(yearsAgoISO(1))
  const [end, setEnd] = useState(todayISO())
  const [initialCash, setInitialCash] = useState(100000)
  const [feeWan, setFeeWan] = useState(3)        // 万分之
  const [slipQian, setSlipQian] = useState(1)   // 千分之
  const [running, setRunning] = useState(false)
  const [discipline, setDiscipline] = useState(true)  // 实盘卖出纪律（止损/止盈/强制减仓）
  const [fetching, setFetching] = useState(false)
  const [fetchMsg, setFetchMsg] = useState<string | null>(null)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  const feeRate = feeWan / 10000
  const slippage = slipQian / 1000

  const setYears = (y: number) => setStart(yearsAgoISO(y))

  const preFetch = async () => {
    setFetching(true); setFetchMsg(null); setError(null)
    try {
      const r = await api.backtestFetchHistory({ universe, lookback_days: 1200 })
      setFetchMsg(`历史缓存：${r.cached}/${r.total} 已就绪，失败 ${r.failed}`)
    } catch (e: any) {
      setError(e.message || '预拉取失败')
    } finally { setFetching(false) }
  }

  const run = async () => {
    setRunning(true); setError(null); setResult(null)
    try {
      const body: any = {
        mode,
        start_date: start,
        end_date: end,
        initial_cash: initialCash,
        fee_rate: feeRate,
        slippage: slippage,
      }
      if (mode === 'portfolio') {
        body.universe = universe
        body.lookback_days = 1200
        body.discipline = discipline
      } else {
        body.codes = codes.split(/[,\s]+/).filter(Boolean)
        body.signal_source = signalSource
      }
      const r = await api.backtestRun(body)
      setResult(r)
    } catch (e: any) {
      setError(e.message || '回测失败')
    } finally { setRunning(false) }
  }

  // 合并权益曲线用于图表
  const chartData = (() => {
    if (!result) return []
    if (result.mode === 'portfolio') {
      const eq = result.equity_curve || []
      const bm = result.benchmark_curve || []
      return eq.map((row: any, i: number) => ({
        date: row[0],
        strategy: row[1],
        benchmark: bm[i] ? bm[i][1] : null,
      }))
    }
    const results = result.results || []
    const allDates = results.length ? results[0].equity_curve.map((r: any) => r[0]) : []
    return allDates.map((d: string, i: number) => {
      const row: any = { date: d }
      results.forEach((res: any, idx: number) => {
        const pt = res.equity_curve[i]
        row[`s${idx}`] = pt ? pt[1] : null
      })
      return row
    })
  })()

  const inputCls = 'w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm ' +
    'focus:outline-none focus:ring-2 focus:ring-primary-500'

  return (
    <div className="p-6 space-y-4">
      <div>
        <h2 className="text-xl font-bold text-gray-800">回测中心</h2>
        <p className="text-sm text-gray-500 mt-1">
          用历史行情重放策略，零成本验证四层漏斗与动量信号的有效性
        </p>
      </div>

      {/* 参数面板 */}
      <div className="card space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <Field label="回测模式">
            <Segmented<Mode>
              value={mode} onChange={setMode}
              options={[
                { value: 'portfolio', label: '组合 · 跟随漏斗' },
                { value: 'single', label: '单标的' },
              ]}
            />
          </Field>
          {mode === 'portfolio' ? (
            <Field label="回测宇宙">
              <Segmented<Universe>
                value={universe} onChange={setUniverse}
                options={[
                  { value: 'whitelist', label: '白名单(100·实盘宇宙)' },
                  { value: 'full', label: '全市场(极慢)' },
                ]}
              />
            </Field>
          ) : (
            <Field label="信号源">
              <Segmented
                value={signalSource}
                onChange={(v) => setSignalSource(v as 'momentum' | 'screening')}
                options={[
                  { value: 'momentum', label: '动量' },
                  { value: 'screening', label: '四层漏斗' },
                ]}
              />
            </Field>
          )}
        </div>

        {mode === 'single' && (
          <Field label="标的代码（逗号分隔）">
            <input className={inputCls} value={codes}
              onChange={(e) => setCodes(e.target.value)}
              placeholder="510300.SH, 159915.SZ" />
          </Field>
        )}

        {mode === 'portfolio' && (
          <Field label="实盘卖出纪律">
            <label className="inline-flex items-center gap-2 cursor-pointer select-none">
              <input type="checkbox" checked={discipline}
                onChange={(e) => setDiscipline(e.target.checked)}
                className="w-4 h-4 accent-blue-600" />
              <span className="text-sm text-gray-700">叠加实盘卖出纪律（止损 / 阶梯止盈 / 强制减仓 / 危险信号）</span>
            </label>
            <p className="text-xs text-gray-400 mt-1">
              开启 = 「跟随系统完整策略」；关闭 = 「买推荐篮、掉出才卖」朴素基线，用于同口径对比买入持有
            </p>
          </Field>
        )}

        <Field label="回测区间">
          <div className="flex items-center gap-2 flex-wrap">
            <input type="date" className={inputCls + ' w-auto'} value={start}
              onChange={(e) => setStart(e.target.value)} />
            <span className="text-gray-400">至</span>
            <input type="date" className={inputCls + ' w-auto'} value={end}
              onChange={(e) => setEnd(e.target.value)} />
            <button className="btn-secondary" onClick={() => setYears(1)}>近1年</button>
            <button className="btn-secondary" onClick={() => setYears(3)}>近3年</button>
            <button className="btn-secondary" onClick={() => setYears(5)}>近5年</button>
          </div>
        </Field>

        <div className="grid grid-cols-3 gap-4">
          <Field label="初始资金(元)">
            <input type="number" className={inputCls} value={initialCash}
              onChange={(e) => setInitialCash(Number(e.target.value))} />
          </Field>
          <Field label="手续费(万分之)">
            <input type="number" className={inputCls} value={feeWan}
              onChange={(e) => setFeeWan(Number(e.target.value))} />
          </Field>
          <Field label="滑点(千分之)">
            <input type="number" className={inputCls} value={slipQian}
              onChange={(e) => setSlipQian(Number(e.target.value))} />
          </Field>
        </div>

        <div className="flex items-center gap-2 pt-1">
          <button className="btn-secondary flex items-center gap-1"
            onClick={preFetch} disabled={fetching || mode !== 'portfolio'}>
            <Download size={14} /> {fetching ? '拉取中…' : '预拉取历史'}
          </button>
          {mode !== 'portfolio' && (
            <span className="text-xs text-gray-400">预拉取仅组合模式需要（单标的需代码已在白名单历史内）</span>
          )}
          <div className="flex-1" />
          <button className="btn-primary flex items-center gap-1"
            onClick={run} disabled={running}>
            <Play size={14} /> {running ? '回测计算中…' : '运行回测'}
          </button>
        </div>
        {fetchMsg && <p className="text-xs text-green-600">{fetchMsg}</p>}
        {error && (
          <div className="flex items-center gap-2 text-sm text-red-600">
            <AlertTriangle size={14} /> {error}
          </div>
        )}
        {mode === 'portfolio' && (
          <p className="text-xs text-gray-400">
            组合回测逐交易日运行四层漏斗（每天一次），白名单(100只)近1年约需 1–3 分钟；
            全市场极慢，建议先用近1年验证再逐步拉长周期。推荐集合已落盘缓存，改费率/资金重跑秒回。
          </p>
        )}
      </div>

      {/* 组合模式结果 */}
      {result && result.mode === 'portfolio' && (
        <>
          <div className="grid grid-cols-4 gap-4">
            <MetricCard title="累计收益" value={`${result.total_return_pct?.toFixed(2)}%`}
              icon={<TrendingUp size={18} />} color={result.total_return_pct! >= 0 ? 'green' : 'red'} />
            <MetricCard title="最大回撤" value={`${result.max_drawdown_pct?.toFixed(2)}%`}
              icon={<Activity size={18} />} color="amber" />
            <MetricCard title="Sharpe" value={`${result.sharpe?.toFixed(2)}`}
              icon={<Percent size={18} />} color="blue" />
            <MetricCard title="胜率" value={`${(result.win_rate! * 100).toFixed(1)}%`}
              icon={<Percent size={18} />} color="purple" />
          </div>
          <div className="grid grid-cols-3 gap-4">
            <MetricCard title="交易次数" value={`${result.trade_count}`} icon={<LineIcon size={18} />} color="blue" />
            <MetricCard title="宇宙规模" value={`${result.universe_size}`} icon={<LineIcon size={18} />} color="blue" />
            <MetricCard title="活跃交易日" value={`${result.active_days}`} icon={<LineIcon size={18} />} color="blue" />
          </div>
          {result.discipline_enabled ? (
            Object.keys(result.discipline_triggers || {}).length > 0 ? (
              <div className="card">
                <h3 className="text-sm font-semibold text-gray-700 mb-3">纪律触发统计（实盘卖出纪律）</h3>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(result.discipline_triggers).map(([k, v]) => (
                    <span key={k} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-red-50 text-red-600 text-xs font-medium">
                      {k} <span className="text-red-400">×{v as number}</span>
                    </span>
                  ))}
                </div>
              </div>
            ) : (
              <div className="card text-sm text-gray-400">本次回测区间未触发任何卖出纪律</div>
            )
          ) : (
            <div className="card text-sm text-amber-600">朴素基线（未启用卖出纪律）：仅「掉出推荐集」才卖出，用于同口径对比买入持有</div>
          )}
          {chartData.length > 0 && (
            <div className="card">
              <h3 className="text-sm font-semibold text-gray-700 mb-3">权益曲线 · 策略 vs 买入持有基准</h3>
              <ResponsiveContainer width="100%" height={320}>
                <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: any) => v == null ? '—' : `¥${Number(v).toLocaleString()}`} />
                  <Legend />
                  <Line type="monotone" dataKey="strategy" name="策略权益" stroke="#3b82f6" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="benchmark" name="买入持有基准" stroke="#94a3b8" strokeWidth={2} strokeDasharray="5 4" dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}

      {/* 单标的模式结果 */}
      {result && result.mode !== 'portfolio' && (
        <>
          <div className="card p-0 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-3 py-2 text-left font-medium text-gray-600">代码</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-600">累计收益</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-600">最大回撤</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-600">Sharpe</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-600">胜率</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-600">交易数</th>
                </tr>
              </thead>
              <tbody>
                {(result.results || []).map((r: any, i: number) => (
                  <tr key={i} className="border-b border-gray-50">
                    <td className="px-3 py-2 font-mono text-gray-700">{r.code}</td>
                    <td className={`px-3 py-2 text-right ${r.total_return_pct >= 0 ? 'text-red-500' : 'text-green-500'}`}>{r.total_return_pct?.toFixed(2)}%</td>
                    <td className="px-3 py-2 text-right text-gray-600">{r.max_drawdown_pct?.toFixed(2)}%</td>
                    <td className="px-3 py-2 text-right text-gray-600">{r.sharpe?.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right text-gray-600">{(r.win_rate * 100).toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right text-gray-600">{r.trade_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {chartData.length > 0 && (
            <div className="card">
              <h3 className="text-sm font-semibold text-gray-700 mb-3">权益曲线（每标的一条）</h3>
              <ResponsiveContainer width="100%" height={320}>
                <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: any) => v == null ? '—' : `¥${Number(v).toLocaleString()}`} />
                  <Legend />
                  {(result.results || []).map((_: any, idx: number) => (
                    <Line key={idx} type="monotone" dataKey={`s${idx}`}
                      name={(result.results || [])[idx].code}
                      stroke={COLORS[idx % COLORS.length]} strokeWidth={1.5} dot={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}

      {!result && !running && !error && (
        <div className="card text-center py-12 text-gray-400">
          <LineIcon size={32} className="mx-auto mb-2 text-gray-300" />
          <p>配置参数后点击「运行回测」</p>
          <p className="text-xs mt-1">组合模式建议先「预拉取历史」把行情落本地</p>
        </div>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-500 mb-1.5">{label}</label>
      {children}
    </div>
  )
}

function Segmented<T extends string>({ value, onChange, options }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: string }[]
}) {
  return (
    <div className="inline-flex bg-gray-100 rounded-lg p-0.5">
      {options.map(opt => (
        <button key={opt.value}
          onClick={() => onChange(opt.value)}
          className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
            value === opt.value ? 'bg-white text-primary-600 shadow-sm font-medium' : 'text-gray-500 hover:text-gray-700'
          }`}>
          {opt.label}
        </button>
      ))}
    </div>
  )
}

function MetricCard({ title, value, icon, color }: { title: string; value: string; icon: React.ReactNode; color: string }) {
  const colorMap: Record<string, string> = {
    blue: 'bg-blue-50 text-blue-600',
    green: 'bg-green-50 text-green-600',
    red: 'bg-red-50 text-red-600',
    purple: 'bg-purple-50 text-purple-600',
    amber: 'bg-amber-50 text-amber-600',
  }
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-gray-500">{title}</span>
        <div className={`p-1.5 rounded ${colorMap[color] || colorMap.blue}`}>{icon}</div>
      </div>
      <p className="text-xl font-bold text-gray-800">{value}</p>
    </div>
  )
}
