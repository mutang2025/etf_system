import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useCallback,
  ReactNode,
} from 'react'

/**
 * Realtime scanner context — the frontend half of the auto-watch daemon.
 *
 * Opens a single EventSource to the backend SSE stream (`/api/scanner/stream`)
 * and exposes a `refreshTick` that increments on every pushed scan result.
 * Pages subscribe to `refreshTick` (via `useLiveRefresh`) to re-fetch their
 * data the moment the daemon finds a new buy/sell signal — no polling, no
 * manual refresh needed while the market is open.
 */

export interface ScannerStatus {
  running: boolean
  scan_count: number
  started_at: string | null
  in_trading_hours: boolean
  scan_interval_seconds: number
  last_scan: ScanPayload | null
  last_error: string | null
}

export interface ScanPayload {
  scan_count?: number
  timestamp?: string
  in_trading_hours?: boolean
  buy?: { scanned: number; triggered: number; signals: any[] }
  sell?: { scanned: number; triggered: number; signals: any[] }
}

interface ScannerContextValue {
  connected: boolean
  status: ScannerStatus | null
  lastScan: ScanPayload | null
  scanCount: number
  refreshTick: number
  live: boolean
  setLive: (v: boolean) => void
  start: () => Promise<void>
  stop: () => Promise<void>
  forceScan: () => Promise<void>
}

const ScannerContext = createContext<ScannerContextValue | null>(null)

async function postJSON(url: string): Promise<any> {
  const resp = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
  if (!resp.ok) throw new Error(`request failed: ${resp.status}`)
  return resp.json()
}

export function ScannerProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false)
  const [status, setStatus] = useState<ScannerStatus | null>(null)
  const [lastScan, setLastScan] = useState<ScanPayload | null>(null)
  const [scanCount, setScanCount] = useState(0)
  const [refreshTick, setRefreshTick] = useState(0)
  const [live, setLive] = useState(true)
  const esRef = useRef<EventSource | null>(null)

  // Initial status snapshot + open SSE stream
  useEffect(() => {
    fetch('/api/scanner/status')
      .then((r) => r.json())
      .then((s: ScannerStatus) => {
        setStatus(s)
        if (typeof s.scan_count === 'number') setScanCount(s.scan_count)
      })
      .catch(() => {})

    const es = new EventSource('/api/scanner/stream')
    esRef.current = es
    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)
    es.onmessage = (e) => {
      try {
        const payload: ScanPayload = JSON.parse(e.data)
        setLastScan(payload)
        const c = payload.scan_count ?? status?.scan_count ?? 0
        setScanCount(c)
        setStatus((s) => (s ? { ...s, last_scan: payload, scan_count: c } : s))
        setRefreshTick((t) => t + 1)
      } catch {
        /* ignore malformed frame */
      }
    }
    return () => {
      es.close()
      esRef.current = null
    }
  }, [])

  const start = useCallback(async () => {
    try {
      const s = await postJSON('/api/scanner/start')
      setStatus(s)
    } catch {}
  }, [])

  const stop = useCallback(async () => {
    try {
      const s = await postJSON('/api/scanner/stop')
      setStatus(s)
    } catch {}
  }, [])

  const forceScan = useCallback(async () => {
    try {
      const payload = await postJSON('/api/scanner/force-scan')
      setLastScan(payload)
      setRefreshTick((t) => t + 1)
    } catch {}
  }, [])

  return (
    <ScannerContext.Provider
      value={{ connected, status, lastScan, scanCount, refreshTick, live, setLive, start, stop, forceScan }}
    >
      {children}
    </ScannerContext.Provider>
  )
}

export function useScanner(): ScannerContextValue {
  const ctx = useContext(ScannerContext)
  if (!ctx) throw new Error('useScanner must be used within <ScannerProvider>')
  return ctx
}

/**
 * Re-fetch `fetcher` whenever the daemon pushes a new scan result (and `live` is on).
 * Uses a ref so the latest closure (e.g. current filter/tab) is always called without
 * re-subscribing the effect on every render.
 */
export function useLiveRefresh(fetcher: () => void | Promise<void>) {
  const { refreshTick, live } = useScanner()
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  useEffect(() => {
    if (live) fetcherRef.current()
  }, [refreshTick, live])
}

/** Small "live" indicator pill for page headers. */
export function LivePill() {
  const { connected, live } = useScanner()
  if (!live) {
    return <span className="badge-gray ml-2 align-middle">手动模式</span>
  }
  return (
    <span
      className={`inline-flex items-center gap-1 ml-2 align-middle px-2 py-0.5 rounded-full text-[10px] font-medium ${
        connected ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-500'
      }`}
    >
      <span className={connected ? 'live-dot live' : 'live-dot off'} />
      {connected ? '实时' : '连接中…'}
    </span>
  )
}
