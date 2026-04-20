import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

/** When `VITE_API_BASE` is unset, the SPA uses same-origin paths; proxy them to FastAPI. */
const devApiTarget =
  process.env.VITE_DEV_PROXY_TARGET ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/health': { target: devApiTarget, changeOrigin: true },
      '/upload': { target: devApiTarget, changeOrigin: true },
      '/documents': { target: devApiTarget, changeOrigin: true },
      '/chat': { target: devApiTarget, changeOrigin: true },
      '/handbook': { target: devApiTarget, changeOrigin: true },
    },
  },
})
