import { useState, useEffect } from 'react'
import { TrendingUp, TrendingDown, Wallet, Bell, AlertCircle, Activity } from 'lucide-react'
import { api } from '../services/api'
import type { DashboardData, IndicesData, IndexQuote } from '../types'
import { useLiveRefresh, LivePill } from '../services/scannerContext'
import { Link } from 'react-router-dom'

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [toast, setToast] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)
  const [indices, setIndices] = useState<IndicesData | null>(null)

  const loadData = async () => {
    try {
      const result = await api.getDashboard()
      setData(result)
    } catch (e) {
      console.error('Failed to load dashboard:', e)
    } finally {
      setLoading(false)
    }
  }

  const runAction = async (
    key: string,
    fn: () => Promise<any>,
    successMsg: (r: any) => string,
  ) => {
    if (busy) return
    setBusy(key)
    setToast(null)
    try {
      const result = await fn()
      await loadData()
      setToast({ type: 'success', msg: successMsg(result) })
    } catch (e: any) {
      setToast({ type: 'error', msg: e?.message || '操作失败，请重试' })
    } finally {
      setBusy(null)
      window.setTimeout(() => setToast(null), 4500)
    }
  }

  useEffect(() => { loadData() }, [])
  useLiveRefresh(loadData)

  const loadIndices = async () => {
    try {
      const res = await api.getIndices()
      setIndices(res)
    } catch (e) {
      console.error('加载指数行情失败:', e)
    }
  }
  useEffect(() => { loadIndices() }, [])

  if (loading) return <div className="p-8 text-center text-gray-500">加载中...</div>
  if (!data) return <div className="p-8 text-center text-red-500">加载失败，请确保后端服务已启动</div>

  const { portfolio, market, performance, pool, signals } = data

  return (
    <div className="p-6 space-y-6">
      {toast && (
        <div className={`fixed top-4 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-xl shadow-lg backdrop-blur-md text-sm font-medium ${
          toast.type === 'success' ? 'bg-emerald-500/90 text-white' : 'bg-red-500/90 text-white'
        }`}>
          {toast.msg}
        </div>
      )}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-800">总览<LivePill /></h2>
          <p className="text-sm text-gray-500 mt-1">{new Date().toLocaleDateString('zh-CN', { dateStyle: 'full' })}</p>
        </div>
        <button
          onClick={() => runAction('refresh', () => Promise.resolve(), () => '看板已刷新')}
          disabled={busy !== null}
          className="btn-secondary disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {busy === 'refresh' ? '刷新中…' : '刷新'}
        </button>
      </div>

      {/* 指数速览 */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-1.5">
            <Activity size={16} className="text-primary-600" /> 指数速览
            {indices && (
              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ${
                indices.data_source === 'akshare' ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-500'
              }`}>
                {indices.data_source === 'akshare' ? '真实行情' : '模拟数据'}
              </span>
            )}
          </h3>
          <div className="flex items-center gap-2">
            <Link to="/trading-board" className="text-xs text-primary-600 hover:underline">查看K线 →</Link>
            {market.is_empty_signal && (
              <div className="flex items-center gap-1 text-red-600">
                <AlertCircle size={14} />
                <span className="text-xs font-medium">空仓信号</span>
              </div>
            )}
            {!market.is_trading_day && <span className="badge-gray text-xs">非交易日</span>}
          </div>
        </div>

        {indices ? (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
              {indices.indices.map((idx: IndexQuote) => {
                const up = idx.change_pct >= 0
                return (
                  <div
                    key={idx.code}
                    className={`flex flex-col rounded-xl border px-3 py-2.5 transition-colors ${
                      up ? 'border-red-100 bg-red-50/40' : 'border-green-100 bg-green-50/40'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-xs font-medium text-gray-700 truncate">{idx.name}</span>
                      <span className="text-[9px] text-gray-400 font-mono shrink-0">{idx.code.split('.')[0]}</span>
                    </div>
                    <p className={`text-lg font-bold mt-1 ${up ? 'text-red-500' : 'text-green-500'}`}>
                      {idx.price.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </p>
                    <span className={`text-xs font-medium ${up ? 'text-red-500' : 'text-green-500'}`}>
                      {up ? '+' : ''}{idx.change_pct.toFixed(2)}%
                    </span>
                  </div>
                )
              })}
            </div>
            {indices.breadth && (
              <div className="flex items-center gap-3 mt-3 text-xs text-gray-500">
                <span className="text-red-500 font-medium">上涨 {indices.breadth.up}</span>
                <span>平盘 {indices.breadth.flat}</span>
                <span className="text-green-500 font-medium">下跌 {indices.breadth.down}</span>
                <span className="ml-auto">涨停 {indices.breadth.limit_up} · 跌停 {indices.breadth.limit_down}</span>
              </div>
            )}
          </>
        ) : (
          <div className="text-sm text-gray-400 py-6 text-center">指数行情加载中…</div>
        )}
      </div>

      {/* Core Metrics */}
      <div className="grid grid-cols-4 gap-4">
        <MetricCard
          title="总资产"
          value={`¥${(portfolio.total_value + portfolio.available_capital).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`}
          subtitle={`可用 ¥${portfolio.available_capital.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`}
          icon={<Wallet size={18} />}
          color="blue"
        />
        <MetricCard
          title="浮动盈亏"
          value={`¥${portfolio.total_pnl.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`}
          subtitle={`${portfolio.total_pnl_pct >= 0 ? '+' : ''}${portfolio.total_pnl_pct.toFixed(2)}%`}
          icon={portfolio.total_pnl >= 0 ? <TrendingUp size={18} /> : <TrendingDown size={18} />}
          color={portfolio.total_pnl >= 0 ? 'green' : 'red'}
        />
        <MetricCard
          title="持仓数量"
          value={`${portfolio.total_positions}`}
          subtitle={`趋势股 ${portfolio.trend_stocks}`}
          icon={<Activity size={18} />}
          color="purple"
        />
        <MetricCard
          title="累计收益率"
          value={`${performance.total_trades > 0 ? `${performance.total_pnl >= 0 ? '+' : ''}¥${performance.total_pnl.toFixed(0)}` : '暂无交易'}`}
          subtitle={`胜率 ${performance.win_rate}% | ${performance.total_trades}笔`}
          icon={<TrendingUp size={18} />}
          color={performance.total_pnl >= 0 ? 'green' : 'red'}
        />
      </div>

      {/* Positions and Signals */}
      <div className="grid grid-cols-2 gap-4">
        {/* Positions */}
        <div className="card">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">持仓概览</h3>
          {portfolio.positions.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-8">暂无持仓</p>
          ) : (
            <div className="space-y-2">
              {portfolio.positions.map(pos => (
                <div key={pos.id} className="flex items-center justify-between text-sm py-2 border-b border-gray-100 last:border-0">
                  <div>
                    <span className="font-medium text-gray-700">{pos.etf_name}</span>
                    {pos.is_trend_stock === 1 && <span className="ml-2 badge-info">趋势股</span>}
                  </div>
                  <div className="text-right">
                    <span className={`font-medium ${pos.pnl_pct >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                      {pos.pnl_pct >= 0 ? '+' : ''}{pos.pnl_pct.toFixed(2)}%
                    </span>
                    <p className="text-xs text-gray-400">持有{pos.hold_days}天</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Recent Signals */}
        <div className="card">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">最近信号</h3>
          {signals.recent.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-8">暂无信号</p>
          ) : (
            <div className="space-y-2">
              {signals.recent.slice(0, 5).map((sig: any) => (
                <div key={sig.signal_id} className="flex items-center justify-between text-sm py-2 border-b border-gray-100 last:border-0">
                  <div className="flex items-center gap-2">
                    <span className={sig.signal_type === 'buy' ? 'badge-success' : sig.signal_type === 'sell' ? 'badge-danger' : 'badge-warning'}>
                      {sig.signal_type === 'buy' ? '买入' : sig.signal_type === 'sell' ? '卖出' : '空仓'}
                    </span>
                    <span className="text-gray-700">{sig.etf_name || sig.etf_code}</span>
                  </div>
                  <span className="text-xs text-gray-400">{sig.trigger_time?.split(' ')[1] || ''}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Quick Actions */}
      <div className="flex flex-wrap gap-3">
        <button
          onClick={() => runAction('screen', () => api.runScreening(), (r) => `选股完成：今日推荐 ${r?.summary?.final_recommended ?? 0} 只`)}
          disabled={busy !== null}
          className="btn-primary disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {busy === 'screen' ? '选股中…' : '运行今日选股'}
        </button>
        <button
          onClick={() => runAction('buy', () => api.scanBuySignals(), (r) => `买入扫描完成：扫描 ${r?.scanned ?? 0} 只，触发 ${r?.triggered ?? 0} 个信号`)}
          disabled={busy !== null}
          className="btn-secondary disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {busy === 'buy' ? '扫描中…' : '扫描买入信号'}
        </button>
        <button
          onClick={() => runAction('sell', () => api.scanSellSignals(), (r) => `卖出扫描完成：扫描 ${r?.scanned ?? 0} 只，触发 ${r?.triggered ?? 0} 个信号`)}
          disabled={busy !== null}
          className="btn-secondary disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {busy === 'sell' ? '扫描中…' : '扫描卖出信号'}
        </button>
      </div>
    </div>
  )
}

function MetricCard({ title, value, subtitle, icon, color }: { title: string; value: string; subtitle?: string; icon: React.ReactNode; color: string }) {
  const colorMap: Record<string, string> = {
    blue: 'bg-blue-50 text-blue-600',
    green: 'bg-green-50 text-green-600',
    red: 'bg-red-50 text-red-600',
    purple: 'bg-purple-50 text-purple-600',
  }
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-gray-500">{title}</span>
        <div className={`p-1.5 rounded ${colorMap[color] || colorMap.blue}`}>{icon}</div>
      </div>
      <p className="text-xl font-bold text-gray-800">{value}</p>
      {subtitle && <p className="text-xs text-gray-400 mt-1">{subtitle}</p>}
    </div>
  )
}
