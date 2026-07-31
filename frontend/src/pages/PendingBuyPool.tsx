import { useState, useEffect, useCallback } from 'react'
import {
  ShoppingCart, Trash2, TrendingUp, TrendingDown,
  RefreshCw, Layers, ArrowRight,
} from 'lucide-react'
import { api } from '../services/api'
import type { PendingPoolItem } from '../types'
import { useLiveRefresh, LivePill } from '../services/scannerContext'
import ETFKlineModal from '../components/ETFKlineModal'

const STATUS_LABEL: Record<string, string> = {
  watching: '待买入',
  sold: '已卖出',
}

// A股配色：涨红跌绿
function pctClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'text-gray-400'
  return v >= 0 ? 'text-red-500' : 'text-green-500'
}
function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '-'
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

// 入池后盈亏百分比：(当前价/卖出价 - 入池点位) / 入池点位
// watching 用实时价、sold 用已记录的 pnl_pct（或卖出价回算），A股红涨绿跌
function entryPnlPct(it: PendingPoolItem): number | null | undefined {
  if (it.status === 'sold') {
    if (it.pnl_pct != null) return it.pnl_pct
    if (it.sell_price != null && it.entry_price) {
      return (it.sell_price - it.entry_price) / it.entry_price * 100
    }
    return null
  }
  if (it.entry_price && it.current_price) {
    return (it.current_price - it.entry_price) / it.entry_price * 100
  }
  return null
}

export default function PendingBuyPool() {
  const [items, setItems] = useState<PendingPoolItem[]>([])
  const [filter, setFilter] = useState<string>('all') // all | watching | sold
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null) // code 正在操作
  const [toast, setToast] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)
  const [detailCode, setDetailCode] = useState<string | null>(null)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.getPendingPool(filter === 'all' ? undefined : filter)
      setItems(res.data || [])
    } catch (e: any) {
      console.error('加载待买入池失败:', e)
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => { loadData() }, [loadData])
  useLiveRefresh(loadData)

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 2600)
    return () => clearTimeout(t)
  }, [toast])

  const handleBuy = async (code: string, name: string) => {
    setBusy(code)
    try {
      await api.buyFromPool(code)
      setToast({ type: 'success', msg: `已从待买入池买入并建仓：${name}` })
      loadData()
    } catch (e: any) {
      setToast({ type: 'error', msg: e.message || '买入失败' })
    } finally {
      setBusy(null)
    }
  }

  const handleRemove = async (code: string, name: string) => {
    setBusy(code)
    try {
      await api.removeFromPool(code)
      setToast({ type: 'success', msg: `已移出待买入池：${name}` })
      loadData()
    } catch (e: any) {
      setToast({ type: 'error', msg: e.message || '移出失败' })
    } finally {
      setBusy(null)
    }
  }

  const watchingCount = items.filter(i => i.status === 'watching').length
  const soldCount = items.filter(i => i.status === 'sold').length

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-blue-50">
            <ShoppingCart className="text-blue-500" size={22} />
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-800 flex items-center gap-2">
              待买入池<LivePill />
            </h2>
            <p className="text-sm text-gray-500">
              买入信号自动入池 · 卖出扫描覆盖池子 · 人工从池子买入/移出
            </p>
          </div>
        </div>
        <button
          onClick={loadData}
          className="flex items-center gap-1 px-3 py-2 text-sm rounded-lg border border-gray-200 hover:bg-gray-50"
        >
          <RefreshCw size={15} /> 刷新
        </button>
      </div>

      {toast && (
        <div className={`mb-4 px-4 py-3 rounded-lg text-sm ${toast.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
          {toast.msg}
        </div>
      )}

      {/* 状态筛选 + 概览 */}
      <div className="flex items-center gap-3 mb-4">
        {(['all', 'watching', 'sold'] as const).map(s => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={`px-3 py-1.5 text-sm rounded-full border transition ${filter === s ? 'bg-blue-500 text-white border-blue-500' : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'}`}
          >
            {s === 'all' ? '全部' : STATUS_LABEL[s]}
            {s === 'watching' && <span className="ml-1 opacity-70">{watchingCount}</span>}
            {s === 'sold' && <span className="ml-1 opacity-70">{soldCount}</span>}
          </button>
        ))}
      </div>

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-gray-600">
              <th className="px-4 py-3 text-left font-medium">代码 / 名称</th>
              <th className="px-4 py-3 text-right font-medium">入池点位</th>
              <th className="px-4 py-3 text-right font-medium">综合得分</th>
              <th className="px-4 py-3 text-right font-medium">现价</th>
              <th className="px-4 py-3 text-right font-medium">入池后盈亏</th>
              <th className="px-4 py-3 text-right font-medium">当日涨跌幅</th>
              <th className="px-4 py-3 text-center font-medium">状态</th>
              <th className="px-4 py-3 text-right font-medium">卖出点位 / 盈亏</th>
              <th className="px-4 py-3 text-center font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
              {loading && (
                <tr><td colSpan={9} className="text-center py-8 text-gray-400">加载中...</td></tr>
              )}
              {!loading && items.length === 0 && (
                <tr><td colSpan={9} className="text-center py-10 text-gray-400">
                <Layers className="mx-auto mb-2 text-gray-300" size={28} />
                {filter === 'watching'
                  ? '暂无待买入标的 — 运行买入扫描后信号会自动入池'
                  : '待买入池为空'}
              </td></tr>
            )}
            {!loading && items.map(it => {
              const isSold = it.status === 'sold'
              return (
                <tr
                  key={it.etf_code}
                  onClick={() => setDetailCode(it.etf_code)}
                  className={`cursor-pointer border-t border-gray-100 ${isSold ? 'bg-gray-50/60 opacity-75' : 'hover:bg-gray-50'}`}
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-gray-800">{it.etf_code}</div>
                    <div className="text-xs text-gray-500">{it.etf_name}</div>
                    {it.enter_time && (
                      <div className="text-[11px] text-gray-400">入池 {it.enter_time}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-700">
                    {it.entry_price?.toFixed(3)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono font-semibold text-purple-600">
                    {it.score != null ? it.score.toFixed(2) : '-'}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-700">
                    {it.current_price != null ? it.current_price.toFixed(3) : '-'}
                  </td>
                  <td className={`px-4 py-3 text-right font-mono font-semibold ${pctClass(entryPnlPct(it))}`}>
                    {fmtPct(entryPnlPct(it))}
                  </td>
                  <td className={`px-4 py-3 text-right font-mono ${pctClass(it.change_pct)}`}>
                    {fmtPct(it.change_pct)}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={`inline-block px-2 py-0.5 rounded-full text-xs ${isSold ? 'bg-amber-100 text-amber-700' : 'bg-blue-100 text-blue-700'}`}>
                      {STATUS_LABEL[it.status]}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {isSold ? (
                      <div>
                        <div className="text-gray-500">{it.sell_price?.toFixed(3)}</div>
                        <div className={pctClass(it.pnl_pct)}>{fmtPct(it.pnl_pct)}</div>
                      </div>
                    ) : (
                      <span className="text-gray-300">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-center gap-2">
                      {!isSold && (
                        <button
                          disabled={busy === it.etf_code}
                          onClick={(e) => { e.stopPropagation(); handleBuy(it.etf_code, it.etf_name) }}
                          className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50"
                        >
                          {busy === it.etf_code ? <RefreshCw size={13} className="animate-spin" /> : <ArrowRight size={13} />}
                          买入
                        </button>
                      )}
                      <button
                        disabled={busy === it.etf_code}
                        onClick={(e) => { e.stopPropagation(); handleRemove(it.etf_code, it.etf_name) }}
                        className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-100 disabled:opacity-50"
                      >
                        <Trash2 size={13} /> 移出
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-xs text-gray-400 leading-relaxed">
        说明：买入信号产生后自动进入本池并记录入池点位；卖出扫描会同步覆盖池子（以入池点位为成本，命中同持仓卖出信号即标记卖出、记录卖出点位与盈亏、状态置「已卖出」），已卖出项不再纳入买入扫描。
        「入池后盈亏」= (现价/卖出价 − 入池点位) ÷ 入池点位，待买入项随实时价变动、已卖出项为已实现盈亏。
        从池子「买入」将按实时价建仓并自动移出；「移出」为人工操作，可移除待买入或已卖出项。
      </p>
      {detailCode && (
        <ETFKlineModal code={detailCode} onClose={() => setDetailCode(null)} />
      )}
    </div>
  )
}
