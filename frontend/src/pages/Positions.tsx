import { useState, useEffect } from 'react'
import { RefreshCw, Wallet, TrendingUp, TrendingDown } from 'lucide-react'
import { api } from '../services/api'
import type { Position, PortfolioSummary } from '../types'
import { useLiveRefresh, LivePill } from '../services/scannerContext'

export default function Positions() {
  const [positions, setPositions] = useState<Position[]>([])
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [sellingId, setSellingId] = useState<number | null>(null)
  const [sellPrice, setSellPrice] = useState('')
  const [sellStrategy, setSellStrategy] = useState('manual')
  const [tab, setTab] = useState<'holding' | 'sold'>('holding')

  const loadData = async () => {
    setLoading(true)
    try {
      const [posResult, summResult] = await Promise.all([
        api.getPositions(tab),
        api.getPortfolioSummary(),
      ])
      setPositions(posResult.data)
      setSummary(summResult)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadData() }, [tab])
  useLiveRefresh(loadData)

  const handleSell = async (pos: Position) => {
    try {
      await api.sellPosition(pos.id!, {
        sell_price: parseFloat(sellPrice) || pos.current_price,
        sell_strategy: sellStrategy,
      })
      setSellingId(null)
      setSellPrice('')
      await loadData()
    } catch (e) {
      alert('卖出失败: ' + (e as Error).message)
    }
  }

  const strategies = ['紧急熔断', '高开砸盘', '危险信号', '趋势分析', '止盈止损', '冲高回落', '强制减仓', '手动']

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-800">持仓看板<LivePill /></h2>
          <p className="text-sm text-gray-500 mt-1">持仓管理与盈亏跟踪</p>
        </div>
        <button onClick={loadData} className="btn-secondary">
          <RefreshCw size={16} className="inline mr-1" /> 刷新
        </button>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-4 gap-4">
          <div className="card">
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm text-gray-500">总市值</span>
              <Wallet size={16} className="text-blue-400" />
            </div>
            <p className="text-lg font-bold text-gray-800">¥{summary.total_value.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</p>
            <p className="text-xs text-gray-400 mt-1">投入 ¥{summary.total_cost.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</p>
          </div>
          <div className="card">
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm text-gray-500">浮动盈亏</span>
              {summary.total_pnl >= 0 ? <TrendingUp size={16} className="text-red-400" /> : <TrendingDown size={16} className="text-green-400" />}
            </div>
            <p className={`text-lg font-bold ${summary.total_pnl >= 0 ? 'text-red-500' : 'text-green-500'}`}>
              {summary.total_pnl >= 0 ? '+' : ''}¥{summary.total_pnl.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
            </p>
            <p className={`text-xs mt-1 ${summary.total_pnl_pct >= 0 ? 'text-red-400' : 'text-green-400'}`}>
              {summary.total_pnl_pct >= 0 ? '+' : ''}{summary.total_pnl_pct.toFixed(2)}%
            </p>
          </div>
          <div className="card">
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm text-gray-500">仓位使用</span>
            </div>
            <p className="text-lg font-bold text-gray-800">{summary.position_ratio.toFixed(1)}%</p>
            <div className="w-full bg-gray-200 rounded-full h-1.5 mt-2">
              <div className="bg-primary-500 h-1.5 rounded-full" style={{ width: `${Math.min(summary.position_ratio, 100)}%` }} />
            </div>
          </div>
          <div className="card">
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm text-gray-500">持仓/趋势股</span>
            </div>
            <p className="text-lg font-bold text-gray-800">{summary.total_positions} / {summary.trend_stocks}</p>
            <p className="text-xs text-gray-400 mt-1">可用 ¥{summary.available_capital.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</p>
          </div>
        </div>
      )}

      {/* Tab switch */}
      <div className="flex gap-2 border-b border-gray-200">
        <button onClick={() => setTab('holding')}
          className={`px-4 py-2 text-sm font-medium border-b-2 ${tab === 'holding' ? 'border-primary-600 text-primary-600' : 'border-transparent text-gray-500'}`}>
          持仓中 ({tab === 'holding' ? positions.length : ''})
        </button>
        <button onClick={() => setTab('sold')}
          className={`px-4 py-2 text-sm font-medium border-b-2 ${tab === 'sold' ? 'border-primary-600 text-primary-600' : 'border-transparent text-gray-500'}`}>
          已平仓
        </button>
      </div>

      {/* Positions table */}
      <div className="card p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-3 py-2 text-left font-medium text-gray-600">代码</th>
              <th className="px-3 py-2 text-left font-medium text-gray-600">名称</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">买入价</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">现价</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">持有份额</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">市值</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">盈亏</th>
              <th className="px-3 py-2 text-center font-medium text-gray-600">天数</th>
              <th className="px-3 py-2 text-center font-medium text-gray-600">趋势股</th>
              {tab === 'sold' && <th className="px-3 py-2 text-center font-medium text-gray-600">卖出策略</th>}
              <th className="px-3 py-2 text-center font-medium text-gray-600">操作</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={10} className="text-center py-8 text-gray-400">加载中...</td></tr>
            ) : positions.length === 0 ? (
              <tr><td colSpan={10} className="text-center py-8 text-gray-400">
                {tab === 'holding' ? '暂无持仓' : '暂无已平仓记录'}
              </td></tr>
            ) : positions.map(pos => (
              <tr key={pos.id} className="border-b border-gray-50 hover:bg-gray-50">
                <td className="px-3 py-2 font-mono text-gray-700">{pos.etf_code}</td>
                <td className="px-3 py-2 text-gray-700">{pos.etf_name}</td>
                <td className="px-3 py-2 text-right text-gray-600">{pos.buy_price?.toFixed(4)}</td>
                <td className="px-3 py-2 text-right text-gray-600">
                  {pos.current_price?.toFixed(4) || '-'}
                </td>
                <td className="px-3 py-2 text-right text-gray-600">{pos.buy_shares?.toFixed(0)}</td>
                <td className="px-3 py-2 text-right text-gray-600">¥{(pos.current_value || pos.buy_amount)?.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</td>
                <td className="px-3 py-2 text-right">
                  {tab === 'holding' ? (
                    <span className={`font-medium ${(pos.pnl_pct || 0) >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                      {pos.pnl_pct >= 0 ? '+' : ''}{pos.pnl_pct?.toFixed(2)}%
                      <br />
                      <span className="text-xs">
                        {pos.pnl_amount >= 0 ? '+' : ''}¥{pos.pnl_amount?.toFixed(0)}
                      </span>
                    </span>
                  ) : (
                    <span className={`font-medium ${(pos.sell_pnl_pct || 0) >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                      {pos.sell_pnl_pct! >= 0 ? '+' : ''}{pos.sell_pnl_pct?.toFixed(2)}%
                      <br />
                      <span className="text-xs">
                        {pos.sell_pnl_amount! >= 0 ? '+' : ''}¥{pos.sell_pnl_amount?.toFixed(0)}
                      </span>
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-center text-gray-600">{pos.hold_days}</td>
                <td className="px-3 py-2 text-center">
                  {pos.is_trend_stock ? <span className="badge-info">趋势</span> : '-'}
                </td>
                {tab === 'sold' && (
                  <td className="px-3 py-2 text-center">
                    <span className="badge-gray">{pos.sell_strategy || '-'}</span>
                  </td>
                )}
                <td className="px-3 py-2 text-center">
                  {tab === 'holding' && sellingId === pos.id ? (
                    <div className="flex flex-col gap-1">
                      <input
                        type="number"
                        step="0.001"
                        placeholder="卖出价"
                        value={sellPrice}
                        onChange={e => setSellPrice(e.target.value)}
                        className="px-2 py-1 border border-gray-300 rounded text-xs w-20"
                      />
                      <select
                        value={sellStrategy}
                        onChange={e => setSellStrategy(e.target.value)}
                        className="px-2 py-1 border border-gray-300 rounded text-xs"
                      >
                        {strategies.map(s => <option key={s} value={s}>{s}</option>)}
                      </select>
                      <div className="flex gap-1">
                        <button onClick={() => handleSell(pos)} className="btn-danger text-xs px-2 py-1">确认</button>
                        <button onClick={() => setSellingId(null)} className="btn-secondary text-xs px-2 py-1">取消</button>
                      </div>
                    </div>
                  ) : tab === 'holding' ? (
                    <button onClick={() => {
                      setSellingId(pos.id!)
                      setSellPrice(pos.current_price?.toString() || '')
                      setSellStrategy('手动')
                    }} className="btn-danger text-xs">卖出</button>
                  ) : (
                    <span className="text-xs text-gray-400">{pos.sell_date}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
