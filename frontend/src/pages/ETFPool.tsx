import { useState, useEffect } from 'react'
import { RefreshCw, Search, Ban, CheckCircle } from 'lucide-react'
import { api } from '../services/api'
import type { ETF } from '../types'

export default function ETFPool() {
  const [etfs, setEtfs] = useState<ETF[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [filterStatus, setFilterStatus] = useState('active')
  const [filterType, setFilterType] = useState('')
  const [syncing, setSyncing] = useState(false)

  const loadData = async () => {
    setLoading(true)
    try {
      const result = await api.getETFPool({
        status: filterStatus || undefined,
        etf_type: filterType || undefined,
        page,
        page_size: 20,
      })
      setEtfs(result.data)
      setTotal(result.total)
    } catch (e) {
      console.error('Failed to load ETF pool:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadData() }, [page, filterStatus, filterType])

  const handleSync = async () => {
    setSyncing(true)
    try {
      await api.syncETFPool()
      await loadData()
    } finally {
      setSyncing(false)
    }
  }

  const handleStatusChange = async (code: string, status: string) => {
    await api.updateETFStatus(code, status)
    await loadData()
  }

  const totalPages = Math.ceil(total / 20)

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-800">ETF池管理</h2>
          <p className="text-sm text-gray-500 mt-1">共 {total} 只ETF</p>
        </div>
        <button onClick={handleSync} disabled={syncing} className="btn-primary">
          <RefreshCw size={16} className={`inline mr-1 ${syncing ? 'animate-spin' : ''}`} />
          {syncing ? '同步中...' : '同步ETF池'}
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3">
        <select
          value={filterStatus}
          onChange={e => { setFilterStatus(e.target.value); setPage(1) }}
          className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
        >
          <option value="">全部状态</option>
          <option value="active">活跃</option>
          <option value="excluded">已排除</option>
          <option value="blacklist">黑名单</option>
          <option value="whitelist">白名单</option>
        </select>
        <select
          value={filterType}
          onChange={e => { setFilterType(e.target.value); setPage(1) }}
          className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
        >
          <option value="">全部类型</option>
          <option value="A股">A股</option>
          <option value="跨境">跨境</option>
        </select>
      </div>

      {/* Table */}
      <div className="card overflow-hidden p-0">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-gray-600">代码</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">名称</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">类型</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">题材</th>
              <th className="px-4 py-3 text-right font-medium text-gray-600">日均成交额(万)</th>
              <th className="px-4 py-3 text-right font-medium text-gray-600">总市值(亿)</th>
              <th className="px-4 py-3 text-right font-medium text-gray-600">日涨幅</th>
              <th className="px-4 py-3 text-center font-medium text-gray-600">状态</th>
              <th className="px-4 py-3 text-center font-medium text-gray-600">操作</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={9} className="text-center py-8 text-gray-400">加载中...</td></tr>
            ) : etfs.length === 0 ? (
              <tr><td colSpan={9} className="text-center py-8 text-gray-400">无数据</td></tr>
            ) : etfs.map(etf => (
              <tr key={etf.code} className="border-b border-gray-50 hover:bg-gray-50">
                <td className="px-4 py-3 font-mono text-gray-700">{etf.code}</td>
                <td className="px-4 py-3 text-gray-700">{etf.name}</td>
                <td className="px-4 py-3">
                  <span className={etf.etf_type === 'A股' ? 'badge-info' : 'badge-warning'}>{etf.etf_type}</span>
                </td>
                <td className="px-4 py-3 text-gray-600">{etf.theme || '-'}</td>
                <td className="px-4 py-3 text-right text-gray-600">{etf.avg_amount_20d?.toFixed(0)}</td>
                <td className="px-4 py-3 text-right text-gray-600">{etf.total_market_cap?.toFixed(1)}</td>
                <td className={`px-4 py-3 text-right font-medium ${etf.change_pct == null ? 'text-gray-400' : etf.change_pct >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                  {etf.change_pct == null ? '-' : `${etf.change_pct >= 0 ? '+' : ''}${etf.change_pct.toFixed(2)}%`}
                </td>
                <td className="px-4 py-3 text-center">
                  <span className={
                    etf.status === 'active' ? 'badge-success' :
                    etf.status === 'excluded' ? 'badge-gray' :
                    etf.status === 'blacklist' ? 'badge-danger' : 'badge-info'
                  }>
                    {etf.status === 'active' ? '活跃' : etf.status === 'excluded' ? '已排除' : etf.status === 'blacklist' ? '黑名单' : '白名单'}
                  </span>
                </td>
                <td className="px-4 py-3 text-center">
                  {etf.status !== 'blacklist' ? (
                    <button onClick={() => handleStatusChange(etf.code, 'blacklist')}
                      className="text-xs text-red-500 hover:underline inline-flex items-center gap-1">
                      <Ban size={12} /> 拉黑
                    </button>
                  ) : (
                    <button onClick={() => handleStatusChange(etf.code, 'active')}
                      className="text-xs text-green-500 hover:underline inline-flex items-center gap-1">
                      <CheckCircle size={12} /> 恢复
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
            className="btn-secondary disabled:opacity-50">上一页</button>
          <span className="text-sm text-gray-500">{page} / {totalPages}</span>
          <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages}
            className="btn-secondary disabled:opacity-50">下一页</button>
        </div>
      )}
    </div>
  )
}
