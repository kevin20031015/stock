import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],

  // ── dev 模式：proxy 到本地 Flask ──────────────────────────────────
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:5000',
    },
  },

  // ── preview 模式（npm run preview）：同樣 proxy ───────────────────
  preview: {
    proxy: {
      '/api': 'http://127.0.0.1:5000',
    },
  },

  build: {
    // 關閉 source map，production build 不需要，省記憶體也省磁碟
    sourcemap: false,
  },
})