import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 前端 :5173；后端 FastAPI 在 :8011（EventSource 直连，后端已开 CORS）。
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173 },
})
