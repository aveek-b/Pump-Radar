import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/markets': 'http://127.0.0.1:8000',
      '/stream': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/radar': 'http://127.0.0.1:8000',
      '/alerts': 'http://127.0.0.1:8000',
      '/events': 'http://127.0.0.1:8000',
      '/replay': 'http://127.0.0.1:8000',
      '/openapi.json': 'http://127.0.0.1:8000',
    },
  },
})
