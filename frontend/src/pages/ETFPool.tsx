import { useState, useEffect, useRef } from 'react'
import { RefreshCw, Search, Ban, CheckCircle } from 'lucide-react'
import { api } from '../services/api'
import type { ETF } from '../types'
import ETFKlineModal from '../components/ETFKlineModal'

export default function ETFPool() {
  const [etfs, setEtfs] = useState<ETF[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [themes, setThemes] = useState<string[]>([])

  // 四个筛选字段
  const [filterStatus, setFilterStatus] = useState('active')
  const [filterType, setFilterType] = useState('')
  const [filterCode, setFilterCode] = useState('')   // 代码（模糊）
  const [filterName, setFilterName] = useState('')   // 名称（模糊）
  const [filterTheme, setFilterTheme] = useState('')   // 题材（精确）
  const [detailCode, setDetailCode] = useState<string | null>(null)
  const [detailName, setDetailName] = useState('')

  // 文本输入防抖：避免每敲一个字就打一次接口
  const [debouncedCode, setDebouncedCode] = useState('')
  const [debouncedName, setDebouncedName] = useState('')
  const firstRender = useRef(true)

  useEffect(() => {
    const t = setTimeout(() => setDebouncedCode(filterCode.trim()), 300)
    return () => clearTimeout(t)
  }, [filterCode])

  useEffect(() => {
    const t = setTimeout(() => setDebouncedName(filterName.trim()), 300)
    return () => clearTimeout(t)
  }, [filterName])

  // 题材下拉选项
  useEffect(() => {
    api.getETFPoolThemes().then(r => setThemes(r.themes || [])).catch(() => {})
  }, [])

  const loadData = async () => {
    setLoading(true)
    try {
      const result = await api.getETFPool({
        status: filterStatus || undefined,
        etf_type: filterType || undefined,
        code: debouncedCode || undefined,
        name: debouncedName || undefined,
        theme: filterTheme || undefined,
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

  // 任意筛选项变化都重新拉取；文本输入经过防抖后触发
  useEffect(() => {
    // 首屏由下方初次加载负责，避免与 mount 重复触发
    if (firstRender.current) {
      firstRender.current = false
      loadData()
      return
    }
    setPage(1)
    loadData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterStatus, filterType, debouncedCode, debouncedName, filterTheme])

  // 翻页（page 变化但不重置筛选）
  useEffect(() => {
    if (page === 1) return
    loadData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page])

  const handleSync = async () => {
    setLoading(true)
    try {
      await api.syncETFPool()
      await loadData()
    } finally {
      setLoading(false)
    }
  }

  const handleStatusChange = async (code: string, status: string) => {
    await api.updateETFStatus(code, status)
    await loadData()
  }

  const resetFilters = () => {
    setFilterStatus('active')
    setFilterType('')
    setFilterCode('')
    setFilterName('')
    setFilterTheme('')
    setPage(1)
  }

  const totalPages = Math.ceil(total / 20)

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-800">ETF池管理</h2>
          <p className="text-sm text-gray-500 mt-1">共 {total} 只ETF（筛选后）</p>
        </div>
        <button onClick={handleSync} disabled={loading} className="btn-primary">
          <RefreshCw size={16} className={`inline mr-1 ${loading ? 'animate-spin' : ''}`} />
          {loading ? '同步中...' : '同步ETF池'}
        </button>
      </div>

      {/* Filters — 代码 / 名称 / 类型 / 题材 */}
      <div className="card p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">代码</label>
            <div className="relative">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                value={filterCode}
                onChange={e => setFilterCode(e.target.value)}
                placeholder="模糊匹配代码"
                className="pl-8 pr-3 py-2 border border-gray-300 rounded-lg text-sm bg-white w-44"
              />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">名称</label>
            <div className="relative">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                value={filterName}
                onChange={e => setFilterName(e.target.value)}
                placeholder="模糊匹配名称"
                className="pl-8 pr-3 py-2 border border-gray-300 rounded-lg text-sm bg-white w-44"
              />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">类型</label>
            <select
              value={filterType}
              onChange={e => setFilterType(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
            >
              <option value="">全部类型</option>
              <option value="A股">A股</option>
              <option value="跨境">跨境</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">题材</label>
            <select
              value={filterTheme}
              onChange={e => setFilterTheme(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
            >
              <option value="">全部题材</option>
              {themes.map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          {(filterStatus || filterType || filterCode || filterName || filterTheme) && (
            <button onClick={resetFilters} className="btn-secondary mb-0.5">
              重置筛选
            </button>
          )}
        </div>
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
              <tr
                key={etf.code}
                onClick={() => { setDetailCode(etf.code); setDetailName(etf.name) }}
                className="cursor-pointer border-b border-gray-50 hover:bg-gray-50"
              >
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
                    <button onClick={(e) => { e.stopPropagation(); handleStatusChange(etf.code, 'blacklist') }}
                      className="text-xs text-red-500 hover:underline inline-flex items-center gap-1">
                      <Ban size={12} /> 拉黑
                    </button>
                  ) : (
                    <button onClick={(e) => { e.stopPropagation(); handleStatusChange(etf.code, 'active') }}
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
      {/* ETF K线弹框 */}
      {detailCode && (
        <ETFKlineModal
          code={detailCode}
          name={detailName}
          onClose={() => setDetailCode(null)}
        />
      )}
    </div>
  )
}
