import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Positions from '../Positions'

const holding = [
  {
    id: 1,
    etf_code: '510300',
    etf_name: '沪深300ETF',
    buy_date: '2026-01-01',
    buy_price: 4.0,
    buy_amount: 10000,
    buy_shares: 2500,
    current_price: 4.2,
    current_value: 10500,
    pnl_amount: 500,
    pnl_pct: 5,
    hold_days: 10,
    is_trend_stock: 1,
    status: 'holding',
  },
]

const summary = {
  total_value: 10500,
  total_cost: 10000,
  total_pnl: 500,
  total_pnl_pct: 5,
  total_capital: 100000,
  available_capital: 50000,
  position_ratio: 10,
  trend_stocks: 1,
  total_positions: 1,
}

vi.mock('../../services/api', () => ({
  api: {
    getPositions: vi.fn(),
    getPortfolioSummary: vi.fn(),
    sellPosition: vi.fn(),
  },
}))

vi.mock('../../services/scannerContext', () => ({
  useLiveRefresh: vi.fn(),
  LivePill: () => null,
}))

import { api } from '../../services/api'

describe('Positions — 卖出确认 ↔ 减仓契约', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(api.getPositions as any).mockResolvedValue({ data: holding })
    ;(api.getPortfolioSummary as any).mockResolvedValue(summary)
    ;(api.sellPosition as any).mockResolvedValue({ message: '减仓成功' })
  })

  it('选择"减仓 50%"并确认 → 向后端发送 sell_action=REDUCE_50', async () => {
    render(<Positions />)
    expect(await screen.findByText('510300')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '卖出' }))
    const select = screen.getByRole('combobox') as HTMLSelectElement
    fireEvent.change(select, { target: { value: '减仓 50%' } })
    fireEvent.click(screen.getByRole('button', { name: '确认' }))

    await waitFor(() =>
      expect(api.sellPosition).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ sell_action: 'REDUCE_50' }),
      ),
    )
    const [, body] = (api.sellPosition as any).mock.calls[0]
    expect(body.sell_strategy).toBe('减仓 50%')
  })

  it('默认"手动"走全平路径 → 发送 sell_action=manual', async () => {
    render(<Positions />)
    expect(await screen.findByText('510300')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '卖出' }))
    fireEvent.click(screen.getByRole('button', { name: '确认' }))

    await waitFor(() =>
      expect(api.sellPosition).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ sell_action: 'manual' }),
      ),
    )
  })
})
