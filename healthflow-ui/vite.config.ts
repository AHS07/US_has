import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      '/auth': 'http://localhost:8000',
      '/admin-api': 'http://localhost:8000',
      '/appointments': 'http://localhost:8000',
      '/doctors': 'http://localhost:8000',
      '/doctor': 'http://localhost:8000',
      '/notifications': 'http://localhost:8000',
      '/medicine-catalog': 'http://localhost:8000',
      '/django-admin': 'http://localhost:8000',
      '/media': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
