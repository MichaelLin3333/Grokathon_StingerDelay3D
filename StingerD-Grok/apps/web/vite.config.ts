import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Proxy /api → FastAPI so the browser never needs to reach :8000 directly
// (fixes Cursor preview / LAN hosts where 127.0.0.1:8000 is unreachable).
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
