import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backend = 'http://127.0.0.1:8900';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': { target: backend, changeOrigin: true },
      '/browse': { target: backend, changeOrigin: true },
      '/review': { target: backend, changeOrigin: true },
      '/maintenance': { target: backend, changeOrigin: true },
      '/settings': { target: backend, changeOrigin: true },
      '/health': { target: backend, changeOrigin: true },
    }
  }
})
