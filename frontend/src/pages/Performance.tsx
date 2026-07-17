import { useState, useEffect } from 'react'
import { TrendingUp, Award, AlertTriangle, Percent } from 'lucide-react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  BarChart, Bar, PieChart, Pie, Cell, ResponsiveContainer,
  Legend
} from 'recharts'
import { api } from '../services/api'

interface PerfData {
  stats: any
  monthly: any[]
  strategy_distribution: any[]
  trades: any[]
  pool_history: any[]   // 待买入池「已卖出」历史记录
}

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#6366f1']

export default function Performance() {
  const [data, setData] = useState<PerfData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.getPerformance().then(result => {
      setData(result)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-8 text-center text-gray-500">加载中...</div>

  const poolHistory: any[] = data?.pool_history || []
  const hasTradesData = !!data && data.stats.total_trades > 0
  const hasAnyData = !!data && (hasTradesData || poolHistory.length > 0)
  if (!hasAnyData) {
    return (
      <div className="p-6">
        <h2 className="text-xl font-bold text-gray-800 mb-4">绩效看板</h2>
        <div className="card text-center py-12">
          <TrendingUp size={32} className="mx-auto text-gray-300 mb-2" />
          <p className="text-gray-400">暂无交易记录</p>
          <p className="text-xs text-gray-400 mt-1">完成买入和卖出操作后，绩效数据将在此展示</p>
        </div>
      </div>
    )
  }

  const { stats, monthly, strategy_distribution, trades } = data
  const hasTrades = stats.total_trades >= 10
  const avgPoolPnl = poolHistory.length
    ? poolHistory.reduce((s: number, it: any) => s + (it.pnl_pct || 0), 0) / poolHistory.length
    : 0

  // Prepare cumulative PnL curve data
  const sortedTrades = [...trades].sort((a, b) =>
    (a.sell_date || '').localeCompare(b.sell_date || '')
  )
  let cumulative = 0
  const pnlCurve = sortedTrades.map(t => {
    cumulative += t.sell_pnl_amount || 0
    return {
      date: t.sell_date || '',
      pnl: round(cumulative, 2),
      trade: t.etf_name,
    }
  })

  return (
    <div className="p-6 space-y-4">
      <div>
        <h2 className="text-xl font-bold text-gray-800">绩效看板</h2>
        <p className="text-sm text-gray-500 mt-1">策略表现与历史交易分析</p>
      </div>

      {/* 持仓交易相关模块（无成交记录时隐藏） */}
      {hasTradesData && (
       <>
      {/* Sample size warning */}
      {!hasTrades && (
        <div className="card border-amber-200 bg-amber-50">
          <div className="flex items-center gap-2 text-amber-700">
            <AlertTriangle size={16} />
            <span className="text-sm font-medium">当前交易样本较少（{stats.total_trades}笔），建议持续运行30个交易日后再评估策略</span>
          </div>
        </div>
      )}

      {/* Core metrics */}
      <div className="grid grid-cols-4 gap-4">
        <MetricCard title="累计收益" value={`¥${stats.total_pnl.toFixed(0)}`} icon={<TrendingUp size={18} />} color={stats.total_pnl >= 0 ? 'green' : 'red'} />
        <MetricCard title="胜率" value={`${stats.win_rate}%`} subtitle={`${stats.win_count}胜 / ${stats.loss_count}负`} icon={<Percent size={18} />} color="blue" />
        <MetricCard title="盈亏比" value={stats.profit_loss_ratio.toFixed(2)} subtitle={`均盈¥${stats.avg_profit} / 均亏¥${stats.avg_loss}`} icon={<Award size={18} />} color="purple" />
        <MetricCard title="最大连续亏损" value={`${stats.max_consecutive_losses}次`} subtitle={`最大盈¥${stats.max_profit} / 最大亏¥${stats.max_loss}`} icon={<AlertTriangle size={18} />} color="amber" />
      </div>

      {/* PnL Curve */}
      {pnlCurve.length > 0 && (
        <div className="card">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">累计收益曲线</h3>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={pnlCurve}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip
                formatter={(value: any) => [`¥${value}`, '累计盈亏']}
                labelFormatter={(label) => `日期: ${label}`}
              />
              <Line type="monotone" dataKey="pnl" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Monthly stats and strategy distribution */}
      <div className="grid grid-cols-2 gap-4">
        {/* Monthly */}
        {monthly.length > 0 && (
          <div className="card">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">月度统计</h3>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={monthly}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip formatter={(value: any) => `¥${value.toFixed(2)}`} />
                <Bar dataKey="pnl" name="盈亏">
                  {monthly.map((m, i) => (
                    <Cell key={i} fill={m.pnl >= 0 ? '#10b981' : '#ef4444'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            <table className="w-full text-xs mt-2">
              <thead className="text-gray-500 border-b border-gray-100">
                <tr>
                  <th className="text-left py-1">月份</th>
                  <th className="text-right py-1">交易数</th>
                  <th className="text-right py-1">胜率</th>
                  <th className="text-right py-1">盈亏</th>
                </tr>
              </thead>
              <tbody>
                {monthly.map(m => (
                  <tr key={m.month} className="border-b border-gray-50">
                    <td className="text-left py-1 text-gray-700">{m.month}</td>
                    <td className="text-right text-gray-600">{m.trades}</td>
                    <td className="text-right text-gray-600">{m.win_rate}%</td>
                    <td className={`text-right ${m.pnl >= 0 ? 'text-red-500' : 'text-green-500'}`}>{m.pnl >= 0 ? '+' : ''}¥{m.pnl.toFixed(0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Strategy distribution */}
        {strategy_distribution.length > 0 && (
          <div className="card">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">卖出策略分布</h3>
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={strategy_distribution}
                  dataKey="count"
                  nameKey="strategy"
                  cx="50%" cy="50%"
                  outerRadius={70}
                  label={({ strategy, count }) => `${strategy}: ${count}`}
                  labelLine={false}
                >
                  {strategy_distribution.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
            <table className="w-full text-xs mt-2">
              <thead className="text-gray-500 border-b border-gray-100">
                <tr>
                  <th className="text-left py-1">策略</th>
                  <th className="text-right py-1">次数</th>
                  <th className="text-right py-1">平均盈亏</th>
                </tr>
              </thead>
              <tbody>
                {strategy_distribution.map((s, i) => (
                  <tr key={i} className="border-b border-gray-50">
                    <td className="text-left py-1 text-gray-700">{s.strategy}</td>
                    <td className="text-right text-gray-600">{s.count}</td>
                    <td className={`text-right ${s.avg_pnl >= 0 ? 'text-red-500' : 'text-green-500'}`}>{s.avg_pnl >= 0 ? '+' : ''}¥{s.avg_pnl.toFixed(0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Trade detail table */}
      <div className="card p-0 overflow-x-auto">
        <div className="px-4 py-3 border-b border-gray-200">
          <h3 className="text-sm font-semibold text-gray-700">交易明细</h3>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-3 py-2 text-left font-medium text-gray-600">代码</th>
              <th className="px-3 py-2 text-left font-medium text-gray-600">名称</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">买入价</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">卖出价</th>
              <th className="px-3 py-2 text-center font-medium text-gray-600">持有天数</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">盈亏</th>
              <th className="px-3 py-2 text-center font-medium text-gray-600">卖出策略</th>
            </tr>
          </thead>
          <tbody>
            {trades.slice().reverse().map((t, i) => (
              <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                <td className="px-3 py-2 font-mono text-gray-700">{t.etf_code}</td>
                <td className="px-3 py-2 text-gray-700">{t.etf_name}</td>
                <td className="px-3 py-2 text-right text-gray-600">{t.buy_price?.toFixed(4)}</td>
                <td className="px-3 py-2 text-right text-gray-600">{t.sell_price?.toFixed(4)}</td>
                <td className="px-3 py-2 text-center text-gray-600">{t.hold_days}</td>
                <td className={`px-3 py-2 text-right font-medium ${(t.sell_pnl_pct || 0) >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                  {t.sell_pnl_pct >= 0 ? '+' : ''}{t.sell_pnl_pct?.toFixed(2)}%
                  <br />
                  <span className="text-xs">
                    {t.sell_pnl_amount >= 0 ? '+' : ''}¥{t.sell_pnl_amount?.toFixed(0)}
                  </span>
                </td>
                <td className="px-3 py-2 text-center">
                  <span className="badge-gray">{t.sell_strategy || '-'}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
       </>
      )}

      {/* 待买入池历史记录 */}
      {poolHistory.length > 0 && (
        <div className="card p-0 overflow-x-auto">
          <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-700">待买入池 · 卖出历史</h3>
            <span className="text-xs text-gray-400">
              {poolHistory.length} 笔 · 平均{avgPoolPnl >= 0 ? '+' : ''}{avgPoolPnl.toFixed(2)}%
            </span>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-3 py-2 text-left font-medium text-gray-600">代码</th>
                <th className="px-3 py-2 text-left font-medium text-gray-600">名称</th>
                <th className="px-3 py-2 text-right font-medium text-gray-600">入池点位</th>
                <th className="px-3 py-2 text-right font-medium text-gray-600">卖出点位</th>
                <th className="px-3 py-2 text-center font-medium text-gray-600">持有</th>
                <th className="px-3 py-2 text-right font-medium text-gray-600">盈亏</th>
                <th className="px-3 py-2 text-left font-medium text-gray-600">入池时间</th>
                <th className="px-3 py-2 text-left font-medium text-gray-600">卖出时间</th>
              </tr>
            </thead>
            <tbody>
              {poolHistory.slice().reverse().map((it, i) => {
                const pnl = it.pnl_pct || 0
                const hold = diffDays(it.enter_time, it.sell_time)
                return (
                  <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="px-3 py-2 font-mono text-gray-700">{it.etf_code}</td>
                    <td className="px-3 py-2 text-gray-700">{it.etf_name}</td>
                    <td className="px-3 py-2 text-right text-gray-600">{it.entry_price?.toFixed(3)}</td>
                    <td className="px-3 py-2 text-right text-gray-600">{it.sell_price?.toFixed(3)}</td>
                    <td className="px-3 py-2 text-center text-gray-600">{hold != null ? `${hold}天` : '-'}</td>
                    <td className={`px-3 py-2 text-right font-medium ${pnl >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                      {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}%
                    </td>
                    <td className="px-3 py-2 text-gray-400 text-xs">{it.enter_time || '-'}</td>
                    <td className="px-3 py-2 text-gray-400 text-xs">{it.sell_time || '-'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function round(num: number, decimals: number) {
  const factor = Math.pow(10, decimals)
  return Math.round(num * factor) / factor
}

function diffDays(a?: string, b?: string): number | null {
  if (!a || !b) return null
  const ta = new Date(a.replace(' ', 'T')).getTime()
  const tb = new Date(b.replace(' ', 'T')).getTime()
  if (isNaN(ta) || isNaN(tb)) return null
  return Math.max(0, Math.round((tb - ta) / 86400000))
}

function MetricCard({ title, value, subtitle, icon, color }: { title: string; value: string; subtitle?: string; icon: React.ReactNode; color: string }) {
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
      {subtitle && <p className="text-xs text-gray-400 mt-1">{subtitle}</p>}
    </div>
  )
}
