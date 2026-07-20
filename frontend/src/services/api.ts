import type { IndicesData, IndexKlineData } from '../types'

const API_BASE = '/api';

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!resp.ok) {
    const error = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(error.detail || 'API Error');
  }
  return resp.json();
}

export const api = {
  // Dashboard
  getDashboard: () => request<any>('/dashboard'),

  // ETF Pool
  getETFPool: (params?: { status?: string; etf_type?: string; code?: string; name?: string; theme?: string; page?: number; page_size?: number }) => {
    const search = new URLSearchParams();
    if (params?.status) search.set('status', params.status);
    if (params?.etf_type) search.set('etf_type', params.etf_type);
    if (params?.code) search.set('code', params.code);
    if (params?.name) search.set('name', params.name);
    if (params?.theme) search.set('theme', params.theme);
    if (params?.page) search.set('page', String(params.page));
    if (params?.page_size) search.set('page_size', String(params.page_size));
    return request<any>(`/etf-pool?${search}`);
  },
  getETFPoolThemes: () => request<{ themes: string[] }>('/etf-pool/themes'),
  getETFDetail: (code: string) => request<any>(`/etf-pool/${code}`),
  updateETFStatus: (code: string, status: string) =>
    request<any>(`/etf-pool/${code}/status`, {
      method: 'PUT',
      body: JSON.stringify({ status }),
    }),
  syncETFPool: () => request<any>('/etf-pool/sync', { method: 'POST' }),
  getSyncLogs: () => request<any>('/etf-pool/sync-logs'),

  // Screening
  runScreening: () => request<any>('/screening/run', { method: 'POST' }),
  getScreeningResults: (date?: string) =>
    request<any>(`/screening/results${date ? `?select_date=${date}` : ''}`),

  // Signals
  getSignals: (params?: { signal_type?: string; status?: string; limit?: number }) => {
    const search = new URLSearchParams();
    if (params?.signal_type) search.set('signal_type', params.signal_type);
    if (params?.status) search.set('status', params.status);
    if (params?.limit) search.set('limit', String(params.limit));
    return request<any>(`/signals?${search}`);
  },
  scanBuySignals: () => request<any>('/signals/buy/scan', { method: 'POST' }),
  scanSellSignals: () => request<any>('/signals/sell/scan', { method: 'POST' }),
  confirmBuySignal: (signalId: string, data: { etf_code: string; etf_name: string; buy_price: number; buy_amount: number }) =>
    request<any>(`/signals/${signalId}/confirm`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  skipSignal: (signalId: string) =>
    request<any>(`/signals/${signalId}/skip`, { method: 'POST' }),

  // Positions
  getPositions: (status?: string) =>
    request<any>(`/positions${status ? `?status=${status}` : ''}`),
  getPortfolioSummary: () => request<any>('/positions/summary'),
  sellPosition: (positionId: number, data: { sell_price: number; sell_strategy: string; sell_action?: string }) =>
    request<any>(`/positions/${positionId}/sell`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Strategy Parameters
  getParams: () => request<any>('/strategy/params'),
  updateParam: (data: { key: string; value: string; group: string; description: string }) =>
    request<any>('/strategy/params', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  applyPreset: (preset: string) =>
    request<any>('/strategy/preset', {
      method: 'POST',
      body: JSON.stringify({ preset }),
    }),
  resetParams: () => request<any>('/strategy/reset', { method: 'POST' }),

  // Performance
  getPerformance: () => request<any>('/performance'),

  // Realtime
  getRealtimeQuotes: (codes?: string[]) =>
    request<any>(`/realtime${codes ? `?codes=${codes.join(',')}` : ''}`),
  tickRealtime: () => request<any>('/realtime/tick', { method: 'POST' }),

  // 交易看板 (Market Indices)
  getIndices: () => request<IndicesData>('/indices'),
  getIndexKlines: (code: string, days: number = 60) =>
    request<IndexKlineData>(`/indices/${code}/klines?days=${days}`),

  // 待买入池 (Pending Buy Pool)
  getPendingPool: (status?: string) =>
    request<any>(`/pending-pool${status ? `?status=${status}` : ''}`),
  buyFromPool: (code: string, amount?: number) =>
    request<any>(`/pending-pool/${code}/buy`, {
      method: 'POST',
      body: amount ? JSON.stringify({ amount }) : undefined,
    }),
  removeFromPool: (code: string) =>
    request<any>(`/pending-pool/${code}/remove`, { method: 'POST' }),

  // 回测中心 (Backtest)
  backtestRun: (body: any) =>
    request<any>('/backtest/run', { method: 'POST', body: JSON.stringify(body) }),
  backtestFetchHistory: (body: any) =>
    request<any>('/backtest/fetch-history', { method: 'POST', body: JSON.stringify(body) }),
};
