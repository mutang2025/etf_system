import { useState, useEffect } from 'react'
import { TrendingUp, TrendingDown, Wallet, Bell, AlertCircle, Activity } from 'lucide-react'
import { api } from '../services/api'
import type { DashboardData } from '../types'
import { useLiveRefresh, LivePill } from '../services/scannerContext'

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [toast, setToast] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)

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
          <h2 className="text-xl font-bold text-gray-800">交易看板<LivePill /></h2>
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

      {/* Market Status */}
      <div className={`card ${market.is_empty_signal ? 'border-red-300 bg-red-50' : ''}`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${market.hs300_change >= 0 ? 'bg-red-50' : 'bg-green-50'}`}>
              {market.hs300_change >= 0 ? <TrendingUp className="text-red-500" size={20} /> : <TrendingDown className="text-green-500" size={20} />}
            </div>
            <div>
              <p className="text-sm text-gray-500">沪深300</p>
              <p className={`text-lg font-bold ${market.hs300_change >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                {market.hs300_change >= 0 ? '+' : ''}{market.hs300_change.toFixed(2)}%
              </p>
            </div>
          </div>
          {market.is_empty_signal && (
            <div className="flex items-center gap-2 text-red-600">
              <AlertCircle size={18} />
              <span className="text-sm font-medium">空仓信号</span>
            </div>
          )}
          {!market.is_trading_day && (
            <span className="badge-gray">非交易日</span>
          )}
        </div>
        {market.is_empty_signal && market.empty_reason && (
          <p className="mt-2 text-sm text-red-600">{market.empty_reason}</p>
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
