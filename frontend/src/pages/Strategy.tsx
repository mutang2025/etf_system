import { useState, useEffect } from 'react'
import { Save, RotateCcw, Check } from 'lucide-react'
import { api } from '../services/api'
import type { StrategyParam } from '../types'

const PRESETS = [
  { key: 'conservative', label: '保守型', desc: '趋势30%+动量10%+量能10%+波动20%+技术30%' },
  { key: 'standard', label: '标准型', desc: '趋势25%+动量20%+量能15%+波动10%+技术30%（默认）' },
  { key: 'aggressive', label: '激进型', desc: '趋势30%+动量30%+量能10%+波动5%+技术25%' },
]

const GROUP_LABELS: Record<string, string> = {
  screening: '选股参数',
  factor: '因子权重',
  buy: '买入参数',
  sell: '卖出参数',
  push: '推送参数',
}

export default function Strategy() {
  const [params, setParams] = useState<Record<string, StrategyParam[]>>({})
  const [editing, setEditing] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [savedKeys, setSavedKeys] = useState<Set<string>>(new Set())

  const loadParams = async () => {
    const result = await api.getParams()
    setParams(result.data)
    // Initialize editing values
    const edits: Record<string, string> = {}
    Object.values(result.data).flat().forEach(p => {
      edits[p.param_key] = p.param_value
    })
    setEditing(edits)
  }

  useEffect(() => { loadParams() }, [])

  const handleSave = async (key: string) => {
    const param = Object.values(params).flat().find(p => p.param_key === key)
    if (!param) return
    setSaving(true)
    try {
      await api.updateParam({
        key,
        value: editing[key],
        group: param.param_group,
        description: param.description,
      })
      setSavedKeys(prev => new Set(prev).add(key))
      setTimeout(() => setSavedKeys(prev => { const n = new Set(prev); n.delete(key); return n }), 2000)
    } finally {
      setSaving(false)
    }
  }

  const handlePreset = async (preset: string) => {
    await api.applyPreset(preset)
    await loadParams()
    alert('预设模板已应用')
  }

  const handleReset = async () => {
    if (!confirm('确认重置所有参数为默认值？')) return
    await api.resetParams()
    await loadParams()
    alert('参数已重置')
  }

  // Check if factor weights sum to 100%
  const factorParams = params['factor'] || []
  const factorSum = factorParams.reduce((sum, p) => sum + (parseFloat(editing[p.param_key]) || 0), 0)
  const factorValid = Math.abs(factorSum - 1.0) < 0.001 // weights are decimals (0.25 = 25%)

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-800">策略参数配置</h2>
          <p className="text-sm text-gray-500 mt-1">修改仅影响下一个选股周期，不影响当前持仓</p>
        </div>
        <button onClick={handleReset} className="btn-secondary">
          <RotateCcw size={16} className="inline mr-1" /> 恢复默认
        </button>
      </div>

      {/* Preset Templates */}
      <div className="card">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">预设模板</h3>
        <div className="grid grid-cols-3 gap-3">
          {PRESETS.map(preset => (
            <button
              key={preset.key}
              onClick={() => handlePreset(preset.key)}
              className="border border-gray-200 rounded-lg p-3 hover:border-primary-400 hover:bg-primary-50 transition-colors text-left"
            >
              <p className="font-medium text-sm text-gray-700">{preset.label}</p>
              <p className="text-xs text-gray-400 mt-1">{preset.desc}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Factor weight validation */}
      {factorParams.length > 0 && (
        <div className={`card ${factorValid ? 'border-green-200' : 'border-red-200'}`}>
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-gray-700">因子权重总和</span>
            <span className={`text-sm font-bold ${factorValid ? 'text-green-600' : 'text-red-600'}`}>
              {(factorSum * 100).toFixed(0)}% {factorValid ? '✅' : '(需等于100%)'}
            </span>
          </div>
        </div>
      )}

      {/* Parameter groups */}
      {Object.entries(GROUP_LABELS).map(([group, label]) => {
        const groupParams = params[group] || []
        if (groupParams.length === 0) return null
        return (
          <div key={group} className="card">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">{label}</h3>
            <div className="grid grid-cols-2 gap-4">
              {groupParams.map(param => (
                <div key={param.param_key} className="flex items-center justify-between">
                  <div className="flex-1">
                    <label className="text-sm text-gray-600">{param.description}</label>
                    <p className="text-xs text-gray-400 font-mono">{param.param_key}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      value={editing[param.param_key] ?? param.param_value}
                      onChange={e => setEditing({ ...editing, [param.param_key]: e.target.value })}
                      className="px-2 py-1 border border-gray-300 rounded text-sm w-24 text-right"
                    />
                    {savedKeys.has(param.param_key) ? (
                      <Check size={16} className="text-green-500" />
                    ) : (
                      <button
                        onClick={() => handleSave(param.param_key)}
                        disabled={saving}
                        className="btn-secondary text-xs px-2 py-1"
                      >
                        <Save size={12} className="inline" /> 保存
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
