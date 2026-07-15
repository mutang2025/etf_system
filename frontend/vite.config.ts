import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // Ensure Server-Sent Events stream through without buffering
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes, _req, res) => {
            const ct = (proxyRes.headers['content-type'] as string) || ''
            if (ct.includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache, no-transform'
              proxyRes.headers['connection'] = 'keep-alive'
              if (typeof (res as any).flushHeaders === 'function') {
                ;(res as any).flushHeaders()
              }
            }
          })
        },
      },
    },
  },
})
