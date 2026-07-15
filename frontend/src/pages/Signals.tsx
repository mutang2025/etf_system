import { useState, useEffect } from 'react'
import { RefreshCw, Check, X, Bell } from 'lucide-react'
import { api } from '../services/api'
import type { BuySignal } from '../types'
import { useLiveRefresh, LivePill } from '../services/scannerContext'

export default function Signals() {
  const [signals, setSignals] = useState<BuySignal[]>([])
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [filterType, setFilterType] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [buyPrice, setBuyPrice] = useState('')
  const [buyAmount, setBuyAmount] = useState('')

  const loadSignals = async () => {
    setLoading(true)
    try {
      const result = await api.getSignals({
        signal_type: filterType || undefined,
        status: filterStatus || undefined,
        limit: 100,
      })
      setSignals(result.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadSignals() }, [filterType, filterStatus])
  useLiveRefresh(loadSignals)

  const scanBuy = async () => {
    setScanning(true)
    try {
      await api.scanBuySignals()
      await loadSignals()
    } finally {
      setScanning(false)
    }
  }

  const scanSell = async () => {
    setScanning(true)
    try {
      await api.scanSellSignals()
      await loadSignals()
    } finally {
      setScanning(false)
    }
  }

  const handleConfirm = async (signal: BuySignal) => {
    try {
      await api.confirmBuySignal(signal.signal_id, {
        etf_code: signal.etf_code,
        etf_name: signal.etf_name,
        buy_price: parseFloat(buyPrice) || signal.price,
        buy_amount: parseFloat(buyAmount) || signal.suggested_amount,
      })
      setConfirmingId(null)
      setBuyPrice('')
      setBuyAmount('')
      await loadSignals()
    } catch (e) {
      alert('确认失败: ' + (e as Error).message)
    }
  }

  const handleSkip = async (signalId: string) => {
    await api.skipSignal(signalId)
    await loadSignals()
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-800">信号中心<LivePill /></h2>
          <p className="text-sm text-gray-500 mt-1">买入/卖出信号管理</p>
        </div>
        <div className="flex gap-2">
          <button onClick={scanBuy} disabled={scanning} className="btn-primary">
            <RefreshCw size={16} className={`inline mr-1 ${scanning ? 'animate-spin' : ''}`} />
            扫描买入
          </button>
          <button onClick={scanSell} disabled={scanning} className="btn-secondary">
            <RefreshCw size={16} className={`inline mr-1 ${scanning ? 'animate-spin' : ''}`} />
            扫描卖出
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3">
        <select
          value={filterType}
          onChange={e => setFilterType(e.target.value)}
          className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
        >
          <option value="">全部类型</option>
          <option value="buy">买入</option>
          <option value="sell">卖出</option>
          <option value="empty">空仓</option>
        </select>
        <select
          value={filterStatus}
          onChange={e => setFilterStatus(e.target.value)}
          className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
        >
          <option value="">全部状态</option>
          <option value="pending">待处理</option>
          <option value="confirmed">已确认</option>
          <option value="skipped">已跳过</option>
        </select>
      </div>

      {/* Signal cards */}
      {loading ? (
        <div className="text-center py-8 text-gray-400">加载中...</div>
      ) : signals.length === 0 ? (
        <div className="card text-center py-12">
          <Bell size={32} className="mx-auto text-gray-300 mb-2" />
          <p className="text-gray-400">暂无信号</p>
        </div>
      ) : (
        <div className="space-y-3">
          {signals.map(sig => (
            <div key={sig.signal_id} className={`card border-l-4 ${
              sig.signal_type === 'buy' ? 'border-l-green-500' :
              sig.signal_type === 'sell' ? 'border-l-red-500' : 'border-l-amber-500'
            }`}>
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded ${
                      sig.signal_type === 'buy' ? 'bg-green-100 text-green-700' :
                      sig.signal_type === 'sell' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
                    }`}>
                      {sig.signal_type === 'buy' ? '买入' : sig.signal_type === 'sell' ? '卖出' : '空仓'}
                    </span>
                    <span className="font-mono text-sm text-gray-700">{sig.etf_code}</span>
                    <span className="text-sm font-medium text-gray-800">{sig.etf_name}</span>
                    {sig.sell_strategy && (
                      <span className="badge-info">策略: {sig.sell_strategy}</span>
                    )}
                    {sig.sell_priority && (
                      <span className="badge-gray">优先级: {sig.sell_priority}</span>
                    )}
                  </div>

                  <div className="grid grid-cols-4 gap-3 text-sm">
                    <div>
                      <span className="text-gray-400">价格</span>
                      <p className="font-medium text-gray-700">{sig.price?.toFixed(4) || '-'}</p>
                    </div>
                    <div>
                      <span className="text-gray-400">涨跌幅</span>
                      <p className={`font-medium ${sig.change_pct >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                        {sig.change_pct >= 0 ? '+' : ''}{sig.change_pct?.toFixed(2)}%
                      </p>
                    </div>
                    {sig.signal_type === 'buy' && (
                      <div>
                        <span className="text-gray-400">建议金额</span>
                        <p className="font-medium text-gray-700">¥{sig.suggested_amount?.toLocaleString()}</p>
                      </div>
                    )}
                    {sig.signal_type === 'sell' && (
                      <>
                        <div>
                          <span className="text-gray-400">盈亏</span>
                          <p className={`font-medium ${(sig.pnl_pct || 0) >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                            {sig.pnl_pct >= 0 ? '+' : ''}{sig.pnl_pct?.toFixed(2)}%
                          </p>
                        </div>
                        <div>
                          <span className="text-gray-400">操作</span>
                          <p className="font-medium text-gray-700">{sig.sell_action}</p>
                        </div>
                      </>
                    )}
                  </div>

                  {/* Trigger details */}
                  {sig.trigger_details && typeof sig.trigger_details === 'object' && (
                    <div className="mt-3 text-xs text-gray-500 bg-gray-50 rounded p-2">
                      {Object.entries(sig.trigger_details.conditions || sig.trigger_details).slice(0, 3).map(([k, v]: [string, any]) => (
                        <div key={k}>
                          <span className="font-medium">{v.name || k}:</span> {v.detail || JSON.stringify(v)}
                        </div>
                      ))}
                    </div>
                  )}

                  <p className="mt-2 text-xs text-gray-400">触发时间: {sig.trigger_time}</p>
                </div>

                {/* Action buttons */}
                {sig.status === 'pending' && sig.signal_type === 'buy' && (
                  <div className="flex flex-col gap-2 ml-4">
                    {confirmingId === sig.signal_id ? (
                      <div className="space-y-2">
                        <input
                          type="number"
                          step="0.001"
                          placeholder="买入价"
                          value={buyPrice}
                          onChange={e => setBuyPrice(e.target.value)}
                          className="px-2 py-1 border border-gray-300 rounded text-sm w-24"
                        />
                        <input
                          type="number"
                          step="100"
                          placeholder="买入金额"
                          value={buyAmount}
                          onChange={e => setBuyAmount(e.target.value)}
                          className="px-2 py-1 border border-gray-300 rounded text-sm w-24"
                        />
                        <button onClick={() => handleConfirm(sig)} className="btn-primary text-xs px-2 py-1">确认</button>
                        <button onClick={() => setConfirmingId(null)} className="btn-secondary text-xs px-2 py-1">取消</button>
                      </div>
                    ) : (
                      <>
                        <button onClick={() => {
                          setConfirmingId(sig.signal_id)
                          setBuyPrice(sig.price?.toString() || '')
                          setBuyAmount(sig.suggested_amount?.toString() || '')
                        }} className="btn-primary text-xs">
                          <Check size={12} className="inline" /> 已买入
                        </button>
                        <button onClick={() => handleSkip(sig.signal_id)} className="btn-secondary text-xs">
                          <X size={12} className="inline" /> 跳过
                        </button>
                      </>
                    )}
                  </div>
                )}
                {sig.status !== 'pending' && (
                  <span className="badge-gray ml-4">{sig.status === 'confirmed' ? '已确认' : sig.status === 'skipped' ? '已跳过' : sig.status}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
