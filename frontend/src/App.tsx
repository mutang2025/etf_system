import { Routes, Route, NavLink } from 'react-router-dom'
import { LayoutDashboard, Database, Filter, Bell, Wallet, Settings, TrendingUp } from 'lucide-react'
import Dashboard from './pages/Dashboard'
import ETFPool from './pages/ETFPool'
import Screening from './pages/Screening'
import Signals from './pages/Signals'
import Positions from './pages/Positions'
import Strategy from './pages/Strategy'
import Performance from './pages/Performance'

const navItems = [
  { path: '/', label: '看板', icon: LayoutDashboard },
  { path: '/etf-pool', label: 'ETF池管理', icon: Database },
  { path: '/screening', label: '四层选股', icon: Filter },
  { path: '/signals', label: '信号中心', icon: Bell },
  { path: '/positions', label: '持仓看板', icon: Wallet },
  { path: '/strategy', label: '策略设置', icon: Settings },
  { path: '/performance', label: '绩效看板', icon: TrendingUp },
]

export default function App() {
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 bg-white border-r border-gray-200 flex flex-col flex-shrink-0">
        <div className="h-16 flex items-center justify-center border-b border-gray-200">
          <h1 className="text-base font-bold text-primary-600">ETF量化交易系统</h1>
        </div>
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
        </Routes>
      </main>
    </div>
  )
}
