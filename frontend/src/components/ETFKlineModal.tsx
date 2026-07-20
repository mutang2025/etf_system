import { useEffect, useMemo, useState } from 'react'
import { X } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { api } from '../services/api'

// 中国 A 股配色：涨=红，跌=绿
const UP = '#dc2626'
const DOWN = '#059669'

function fmtNum(n: number, digits = 2): string {
  return n.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

type CandlePayload = { date: string; open: number; high: number; low: number; close: number }

// recharts 没有原生蜡烛图，用 Bar + custom shape 实现（与交易看板同款）
function makeCandleShape(yMin: number, yMax: number) {
  return function CandleShape(props: any) {
    const { x, y, width, height, payload } = props as {
      x: number; y: number; width: number; height: number; payload: CandlePayload
    }
    const range = yMax - yMin
    if (!height || range <= 0 || payload.high <= yMin) {
      return <line x1={x + width / 2} y1={y} x2={x + width / 2} y2={y + 1} stroke={UP} />
    }
    // 从 recharts 给的这根“high 到 yMin”的柱子反推出整个图表的像素映射
    const chartHeight = (height * range) / (payload.high - yMin)
    const chartTop = y - chartHeight * (yMax - payload.high) / range
    const yFor = (price: number) => chartTop + chartHeight * (yMax - price) / range

    const isUp = payload.close >= payload.open
    const color = isUp ? UP : DOWN
    const bodyTop = Math.max(payload.open, payload.close)
    const bodyBottom = Math.min(payload.open, payload.close)

    const cx = x + width / 2
    const yHigh = yFor(payload.high)
    const yLow = yFor(payload.low)
    const yBodyTop = yFor(bodyTop)
    const yBodyBottom = yFor(bodyBottom)
    const bodyHeight = Math.max(yBodyBottom - yBodyTop, 1)
    const bodyWidth = Math.max(width * 0.6, 1)
    const bodyX = cx - bodyWidth / 2

    return (
      <g>
        {/* 影线 */}
        <line x1={cx} y1={yHigh} x2={cx} y2={yLow} stroke={color} strokeWidth={1} />
        {/* 实体 */}
        <rect
          x={bodyX} y={yBodyTop} width={bodyWidth} height={bodyHeight}
          fill={color} stroke={color} strokeWidth={1} rx={1}
        />
      </g>
    )
  }
}

function CandleTooltip({ active, payload, label }: any) {
  if (!active || !payload || !payload.length) return null
  const d = payload[0].payload as CandlePayload
  const isUp = d.close >= d.open
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs shadow-sm">
      <div className="mb-1 text-gray-500">{label}</div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        <span className="text-gray-400">开</span>
        <span className="text-right font-mono">{fmtNum(d.open)}</span>
        <span className="text-gray-400">高</span>
        <span className="text-right font-mono">{fmtNum(d.high)}</span>
        <span className="text-gray-400">低</span>
        <span className="text-right font-mono">{fmtNum(d.low)}</span>
        <span className="text-gray-400">收</span>
        <span className={`text-right font-mono font-medium ${isUp ? 'text-red-500' : 'text-green-500'}`}>
          {fmtNum(d.close)}
        </span>
      </div>
    </div>
  )
}

const TIMEFRAMES = [
  { days: 20, label: '近20日' },
  { days: 60, label: '近60日' },
  { days: 120, label: '近120日' },
]

export default function ETFKlineModal({
  code,
  name,
  onClose,
}: {
  code: string
  name?: string
  onClose: () => void
}) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [detail, setDetail] = useState<any>(null)
  const [days, setDays] = useState(60)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.getETFDetail(code, days)
      .then((r) => { if (!cancelled) { setDetail(r); setLoading(false) } })
      .catch((e) => {
        if (!cancelled) {
          setError('加载K线失败，请确认后端服务已启动')
          setLoading(false)
          console.error(e)
        }
      })
    return () => { cancelled = true }
  }, [code, days])

  // ESC 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const candles = useMemo(
    () => (detail?.klines ?? []).map((k: any) => ({
      date: (k.trade_date || '').slice(5),
      open: k.open,
      high: k.high,
      low: k.low,
      close: k.close,
    })),
    [detail],
  )

  const { yMin, yMax } = useMemo(() => {
    if (candles.length === 0) return { yMin: 0, yMax: 1 }
    const lows = candles.map((d: CandlePayload) => d.low)
    const highs = candles.map((d: CandlePayload) => d.high)
    const min = Math.min(...lows)
    const max = Math.max(...highs)
    const pad = Math.max((max - min) * 0.02, 0.01)
    return { yMin: min - pad, yMax: max + pad }
  }, [candles])

  const CandleShape = useMemo(() => makeCandleShape(yMin, yMax), [yMin, yMax])

  const rt = detail?.realtime
  const etf = detail?.etf

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-3">
          <div className="flex items-baseline gap-2">
            <h3 className="text-lg font-bold text-gray-800">{name || etf?.etf_name || code}</h3>
            <span className="font-mono text-xs text-gray-400">{code}</span>
            {rt && (
              <span className={`text-sm font-medium ${rt.change_pct >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                {fmtNum(rt.price)} ({rt.change_pct >= 0 ? '+' : ''}{fmtNum(rt.change_pct)}%)
              </span>
            )}
          </div>
          <button onClick={onClose} className="text-gray-400 transition-colors hover:text-gray-700">
            <X size={18} />
          </button>
        </div>

        {/* Timeframe toggles */}
        <div className="flex items-center gap-1 px-5 pt-3">
          {TIMEFRAMES.map((t) => (
            <button
              key={t.days}
              onClick={() => setDays(t.days)}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                days === t.days
                  ? 'bg-primary-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Chart */}
        <div className="px-5 py-3">
          {loading ? (
            <div className="py-16 text-center text-gray-400">加载中...</div>
          ) : error ? (
            <div className="py-16 text-center text-red-500">{error}</div>
          ) : candles.length > 0 ? (
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={candles} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis
                  dataKey="date" tick={{ fontSize: 11, fill: '#94a3b8' }}
                  minTickGap={28} axisLine={false} tickLine={false}
                />
                <YAxis
                  domain={[yMin, yMax]} tick={{ fontSize: 11, fill: '#94a3b8' }}
                  width={48} axisLine={false} tickLine={false}
                  tickFormatter={(v: number) => fmtNum(v, 0)}
                />
                <Tooltip content={<CandleTooltip />} cursor={{ fill: '#f1f5f9' }} />
                <Bar dataKey="high" shape={CandleShape} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="py-16 text-center text-gray-400">暂无K线数据</div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-4 border-t border-gray-100 px-5 py-3 text-xs text-gray-400">
          <span>中国 A 股惯例：<span className="font-medium text-red-500">红涨</span> / <span className="font-medium text-green-500">绿跌</span></span>
          <span className="ml-auto">按 ESC 或点击遮罩关闭</span>
        </div>
      </div>
    </div>
  )
}
