import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api } from '../api'

describe('api client', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  function mockFetchOnce(body: any = {}, ok = true) {
    const fn = vi.fn().mockResolvedValue({
      ok,
      statusText: ok ? 'OK' : 'ERR',
      json: async () => body,
    })
    // @ts-expect-error test doubles global fetch
    global.fetch = fn
    return fn
  }

  // ===== 卖出确认 ↔ 后端 parse_reduce_ratio 契约 =====
  describe('sellPosition — sell_action contract', () => {
    it('REDUCE_50 → POST 带 sell_action=REDUCE_50', async () => {
      const fetchMock = mockFetchOnce({ message: '减仓成功' })
      await api.sellPosition(7, {
        sell_price: 1.234,
        sell_strategy: '减仓 50%',
        sell_action: 'REDUCE_50',
      })
      expect(fetchMock).toHaveBeenCalledTimes(1)
      const [url, opts] = fetchMock.mock.calls[0]
      expect(url).toBe('/api/positions/7/sell')
      expect(opts.method).toBe('POST')
      const body = JSON.parse(opts.body as string)
      expect(body.sell_action).toBe('REDUCE_50')
      expect(body.sell_price).toBe(1.234)
      expect(body.sell_strategy).toBe('减仓 50%')
    })

    it('CLEAR_ALL → POST 带 sell_action=CLEAR_ALL（全平路径）', async () => {
      const fetchMock = mockFetchOnce({ message: '平仓成功' })
      await api.sellPosition(7, {
        sell_price: 1.234,
        sell_strategy: '全平（清仓）',
        sell_action: 'CLEAR_ALL',
      })
      const [, opts] = fetchMock.mock.calls[0]
      expect(JSON.parse(opts.body as string).sell_action).toBe('CLEAR_ALL')
    })
  })

  // ===== 查询参数序列化（建立 API 客户端测试样板） =====
  describe('query param serialization', () => {
    it('getPositions(status) 追加 ?status=', async () => {
      const fetchMock = mockFetchOnce({ data: [] })
      await api.getPositions('holding')
      const [url] = fetchMock.mock.calls[0]
      expect(url).toBe('/api/positions?status=holding')
    })

    it('getETFPool 序列化多个参数', async () => {
      const fetchMock = mockFetchOnce({ data: [], total: 0 })
      await api.getETFPool({ status: 'active', page: 2, page_size: 50 })
      const [url] = fetchMock.mock.calls[0]
      expect(url).toContain('/api/etf-pool?')
      expect(url).toContain('status=active')
      expect(url).toContain('page=2')
      expect(url).toContain('page_size=50')
    })
  })
})
