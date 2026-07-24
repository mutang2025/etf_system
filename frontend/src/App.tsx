import { Routes, Route, NavLink } from 'react-router-dom'
import { LayoutDashboard, Database, Filter, Bell, Wallet, Settings, TrendingUp, Play, Pause, Zap, BarChart3, ShoppingCart, LineChart } from 'lucide-react'
import Dashboard from './pages/Dashboard'
import ETFPool from './pages/ETFPool'
import Screening from './pages/Screening'
import Signals from './pages/Signals'
import Positions from './pages/Positions'
import Strategy from './pages/Strategy'
import Performance from './pages/Performance'
import TradingBoard from './pages/TradingBoard'
import PendingBuyPool from './pages/PendingBuyPool'
import Backtest from './pages/Backtest'
import { useScanner } from './services/scannerContext'

const navItems = [
  { path: '/', label: '总览', icon: LayoutDashboard },
  { path: '/trading-board', label: '市场看板', icon: BarChart3 },
  { path: '/etf-pool', label: 'ETF池管理', icon: Database },
  { path: '/screening', label: '四层选股', icon: Filter },
  { path: '/signals', label: '信号中心', icon: Bell },
  { path: '/positions', label: '持仓看板', icon: Wallet },
  { path: '/strategy', label: '策略设置', icon: Settings },
  { path: '/performance', label: '绩效看板', icon: TrendingUp },
  { path: '/pending-pool', label: '待买入池', icon: ShoppingCart },
  { path: '/backtest', label: '回测中心', icon: LineChart },
]

function LiveBar() {
  const { connected, status, scanCount, lastScan, live, setLive, start, stop, forceScan } = useScanner()
  const running = status?.running
  const dotClass = !connected ? 'live-dot err' : running ? 'live-dot live' : 'live-dot off'
  const lastTime = lastScan?.timestamp?.split(' ')[1] ?? '—'

  return (
    <div className="mx-3 mb-2 p-2.5 rounded-xl border border-gray-200 bg-gradient-to-b from-gray-50 to-white flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={dotClass} />
          <span className="text-xs font-semibold text-gray-700">
            {running ? '实时盯盘中' : '盯盘已暂停'}
          </span>
        </div>
        <label className="flex items-center gap-1 text-[10px] text-gray-500 cursor-pointer select-none" title="自动刷新开关">
          <input
            type="checkbox"
            checked={live}
            onChange={(e) => setLive(e.target.checked)}
            className="accent-primary-600 w-3 h-3"
          />
          自动
        </label>
      </div>

      <div className="flex items-center justify-between text-[10px] text-gray-400 font-mono">
        <span>已扫描 {scanCount || 0} 次</span>
        <span>最近 {lastTime}</span>
      </div>

      <div className="flex items-center gap-1.5">
        {running ? (
          <button
            onClick={stop}
            className="flex-1 flex items-center justify-center gap-1 text-[10px] px-2 py-1 rounded-lg bg-gray-200 hover:bg-gray-300 text-gray-700 transition-colors"
          >
            <Pause size={11} /> 暂停
          </button>
        ) : (
          <button
            onClick={start}
            className="flex-1 flex items-center justify-center gap-1 text-[10px] px-2 py-1 rounded-lg bg-primary-600 hover:bg-primary-700 text-white transition-colors"
          >
            <Play size={11} /> 启动
          </button>
        )}
        <button
          onClick={forceScan}
          className="flex-1 flex items-center justify-center gap-1 text-[10px] px-2 py-1 rounded-lg bg-gray-200 hover:bg-gray-300 text-gray-700 transition-colors"
          title="立即扫描一次（不受交易时段限制）"
        >
          <Zap size={11} /> 立即扫描
        </button>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 bg-white border-r border-gray-200 flex flex-col flex-shrink-0">
        <div className="h-16 flex items-center justify-center border-b border-gray-200">
          <h1 className="text-base font-bold text-primary-600">ETF量化交易系统</h1>
        </div>
        <LiveBar />
        <nav className="flex-1 py-4 overflow-y-auto">
          {navItems.map(item => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === '/'}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                    isActive
                      ? 'bg-primary-50 text-primary-600 font-medium border-r-2 border-primary-600'
                      : 'text-gray-600 hover:bg-gray-50'
                  }`
                }
              >
                <Icon size={18} />
                {item.label}
              </NavLink>
            )
          })}
        </nav>
        <div className="p-4 text-xs text-gray-400 border-t border-gray-200">
          v1.0.0 - MVP
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/etf-pool" element={<ETFPool />} />
          <Route path="/screening" element={<Screening />} />
          <Route path="/signals" element={<Signals />} />
          <Route path="/positions" element={<Positions />} />
          <Route path="/strategy" element={<Strategy />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/trading-board" element={<TradingBoard />} />
          <Route path="/pending-pool" element={<PendingBuyPool />} />
          <Route path="/backtest" element={<Backtest />} />
        </Routes>
      </main>
    </div>
  )
}
