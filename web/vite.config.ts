import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The gallery calls the backend's /api; in dev, Vite forwards it. In production the backend serves web/dist itself.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8765',
    },
  },
})
