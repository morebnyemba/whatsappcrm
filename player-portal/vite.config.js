import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Player portal dev server on 5174 (admin CRM uses 5173).
export default defineConfig({
  plugins: [react()],
  server: { port: 5174 },
})
