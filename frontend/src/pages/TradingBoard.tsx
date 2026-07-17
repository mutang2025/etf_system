import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  RefreshCw, BarChart3, Activity, TrendingUp, TrendingDown,
  ArrowUpRight, ArrowDownRight, Gauge,
} from 'lucide-react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { api } from '../services/api'
import type { IndicesData, IndexQuote, IndexKlineData, IndexKline } from '../types'

// 中国 A 股配色：涨=红，跌=绿
const UP = '#ef4444'
const DOWN = '#10b981'

function toneColor(pct: number): string {
  return pct >= 0 ? UP : DOWN
}
function toneText(pct: number): string {
  return pct >= 0 ? 'text-red-500' : 'text-green-500'
}
function fmtNum(n: number, digits = 2): string {
  return n.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}
function fmtVol(volume: number): string {
  return `${(volume / 1e8).toFixed(2)} 亿股`
}
function fmtAmt(amount: number): string {
  return `${fmtNum(amount, 0)} 亿`
}

const TIMEFRAMES = [
  { days: 20, label: '近20日' },
  { days: 60, label: '近60日' },
  { days: 120, label: '近120日' },
]

export default function TradingBoard() {
  const [data, setData] = useState<IndicesData | null>(null)
  const [klines, setKlines] = useState<IndexKlineData | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [auto, setAuto] = useState(true)
  const [selected, setSelected] = useState<string>('000001.SH') // 上证指数
  const [tf, setTf] = useState<number>(60)

  const loadQuotes = useCallback(async () => {
    try {
      const result = await api.getIndices()
      setData(result)
    } catch (e) {
      console.error('加载指数行情失败:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  const loadKlines = useCallback(async (code: string, days: number) => {
    try {
      const result = await api.getIndexKlines(code, days)
      setKlines(result)
    } catch (e) {
      console.error('加载指数K线失败:', e)
    }
  }, [])

  // 初次 + 切换指数/周期时拉取 K 线
  useEffect(() => {
    loadKlines(selected, tf)
  }, [selected, tf, loadKlines])

  // 自动刷新报价
  useEffect(() => {
    loadQuotes()
    if (!auto) return
    const t = window.setInterval(loadQuotes, 5000)
    return () => window.clearInterval(t)
  }, [auto, loadQuotes])

  const refresh = () => {
    if (busy) return
    setBusy(true)
    Promise.all([loadQuotes(), loadKlines(selected, tf)])
      .finally(() => window.setTimeout(() => setBusy(false), 400))
  }

  const selectedQuote = useMemo<IndexQuote | undefined>(
    () => data?.indices.find((i) => i.code === selected),
    [data, selected],
  )

  const chartColor = useMemo(() => {
    if (!klines || klines.klines.length < 2) return UP
    const first = klines.klines[0].close
    const last = klines.klines[klines.klines.length - 1].close
    return last >= first ? UP : DOWN
  }, [klines])

  const chartData = useMemo(
    () => (klines?.klines ?? []).map((k: IndexKline) => ({
      date: k.trade_date.slice(5), // MM-DD
      close: k.close,
    })),
    [klines],
  )

  const breadth = data?.breadth
  const breadthTotal = breadth ? breadth.up + breadth.down + breadth.flat : 1

  if (loading) return <div className="p-8 text-center text-gray-500">加载中...</div>
  if (!data) return <div className="p-8 text-center text-red-500">加载失败，请确保后端服务已启动（mock 模式）</div>

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-800 flex items-center gap-2">
            <BarChart3 size={22} className="text-primary-600" /> 交易看板
            <span className={`inline-flex items-center gap-1 ml-1 align-middle px-2 py-0.5 rounded-full text-[10px] font-medium ${
              data.data_source === 'akshare' ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-500'
            }`}>
              {data.data_source === 'akshare' ? '真实行情' : '模拟数据'}
            </span>
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            更新于 {data.updated_at}
            {!data.trading_day && <span className="badge-gray ml-2">非交易日</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs text-gray-500 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={auto}
              onChange={(e) => setAuto(e.target.checked)}
              className="accent-primary-600 w-3 h-3"
            />
            自动刷新(5s)
          </label>
          <button
            onClick={refresh}
            disabled={busy}
            className="btn-secondary disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-1"
          >
            <RefreshCw size={14} className={busy ? 'animate-spin' : ''} />
            {busy ? '刷新中' : '刷新'}
          </button>
        </div>
      </div>

      {/* 市场宽度 */}
      {breadth && (
        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-1.5">
              <Gauge size={16} className="text-primary-600" /> 市场宽度
            </h3>
            <div className="flex items-center gap-3 text-xs">
              <span className="text-red-500 font-medium">涨停 {breadth.limit_up}</span>
              <span className="text-green-500 font-medium">跌停 {breadth.limit_down}</span>
            </div>
          </div>
          <div className="flex h-3 rounded-full overflow-hidden bg-gray-100">
            <div style={{ width: `${(breadth.up / breadthTotal) * 100}%`, background: UP }} />
            <div style={{ width: `${(breadth.flat / breadthTotal) * 100}%`, background: '#cbd5e1' }} />
            <div style={{ width: `${(breadth.down / breadthTotal) * 100}%`, background: DOWN }} />
          </div>
          <div className="flex items-center justify-between mt-2 text-sm">
            <span className="text-red-500 font-semibold">上涨 {breadth.up}</span>
            <span className="text-gray-400">平盘 {breadth.flat}</span>
            <span className="text-green-500 font-semibold">下跌 {breadth.down}</span>
          </div>
        </div>
      )}

      {/* 指数卡片 */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-4">
        {data.indices.map((idx) => {
          const active = idx.code === selected
          const color = toneColor(idx.change_pct)
          return (
            <button
              key={idx.code}
              onClick={() => setSelected(idx.code)}
              className={`card text-left transition-all duration-200 hover:shadow-md ${
                active ? 'ring-2 ring-primary-500 border-primary-200' : 'hover:border-gray-300'
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-700">{idx.name}</span>
                <span className="text-[10px] text-gray-400 font-mono">{idx.code.split('.')[0]}</span>
              </div>
              <p className={`text-2xl font-bold mt-1 ${toneText(idx.change_pct)}`}>{fmtNum(idx.price)}</p>
              <div className="flex items-center justify-between mt-1">
                <span className={`text-sm font-medium ${toneText(idx.change_pct)} flex items-center gap-0.5`}>
                  {idx.change_pct >= 0 ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                  {idx.change >= 0 ? '+' : ''}{fmtNum(idx.change)}
                </span>
                <span className={`text-sm font-medium ${toneText(idx.change_pct)}`}>
                  {idx.change_pct >= 0 ? '+' : ''}{fmtNum(idx.change_pct)}%
                </span>
              </div>
              <div className="flex items-center justify-between mt-2 text-[11px] text-gray-400">
                <span>开 {fmtNum(idx.open)}</span>
                <span>高 {fmtNum(idx.high)}</span>
                <span>低 {fmtNum(idx.low)}</span>
              </div>
            </button>
          )
        })}
      </div>

      {/* 选中指数 K 线 */}
      <div className="card">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-700">{selectedQuote?.name ?? '指数'}</h3>
            {selectedQuote && (
              <span className={`text-sm font-medium ${toneText(selectedQuote.change_pct)}`}>
                {fmtNum(selectedQuote.price)} ({selectedQuote.change_pct >= 0 ? '+' : ''}{fmtNum(selectedQuote.change_pct)}%)
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            {TIMEFRAMES.map((t) => (
              <button
                key={t.days}
                onClick={() => setTf(t.days)}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
                  tf === t.days
                    ? 'bg-primary-600 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={chartData} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="idxFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={chartColor} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={chartColor} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis
                dataKey="date" tick={{ fontSize: 11, fill: '#94a3b8' }}
                minTickGap={28} axisLine={false} tickLine={false}
              />
              <YAxis
                domain={['auto', 'auto']} tick={{ fontSize: 11, fill: '#94a3b8' }}
                width={48} axisLine={false} tickLine={false}
              />
              <Tooltip
                contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e2e8f0' }}
                formatter={(v: number) => [fmtNum(v), '收盘']}
              />
              <ReferenceLine y={selectedQuote?.prev_close} stroke="#94a3b8" strokeDasharray="4 4" />
              <Area
                type="monotone" dataKey="close" stroke={chartColor} strokeWidth={2}
                fill="url(#idxFill)" dot={false} activeDot={{ r: 3 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="text-center text-gray-400 py-12">暂无K线数据</div>
        )}

        {selectedQuote && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4 text-sm">
            <Metric label="今开" value={fmtNum(selectedQuote.open)} />
            <Metric label="最高" value={fmtNum(selectedQuote.high)} />
            <Metric label="最低" value={fmtNum(selectedQuote.low)} />
            <Metric label="昨收" value={fmtNum(selectedQuote.prev_close)} />
            <Metric label="成交量" value={fmtVol(selectedQuote.volume)} />
            <Metric label="成交额" value={fmtAmt(selectedQuote.amount)} />
            <Metric label="涨跌点" value={`${selectedQuote.change >= 0 ? '+' : ''}${fmtNum(selectedQuote.change)}`} color={toneText(selectedQuote.change_pct)} />
            <Metric label="涨跌幅" value={`${selectedQuote.change_pct >= 0 ? '+' : ''}${fmtNum(selectedQuote.change_pct)}%`} color={toneText(selectedQuote.change_pct)} />
          </div>
        )}
      </div>

      {/* 图例提示 */}
      <div className="flex items-center gap-4 text-xs text-gray-400 px-1">
        <Activity size={13} />
        <span>中国 A 股惯例：<span className="text-red-500 font-medium">红涨</span> / <span className="text-green-500 font-medium">绿跌</span></span>
        <span className="ml-auto">虚线为昨收参考位</span>
      </div>
    </div>
  )
}

function Metric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex flex-col bg-gray-50 rounded-lg px-3 py-2">
      <span className="text-[11px] text-gray-400">{label}</span>
      <span className={`text-sm font-semibold text-gray-700 ${color ?? ''}`}>{value}</span>
    </div>
  )
}
