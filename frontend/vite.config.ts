import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Where the backend listens; set BACKEND_URL when it is not on the default port
const backend = process.env.BACKEND_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true,
      },
      // The protected Weekend Saver app, including its one-time link and event stream
      '/ws': {
        target: backend,
        changeOrigin: true,
      },
    },
  },
})
