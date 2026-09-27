import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': process.env.DWG3D_API ?? 'http://127.0.0.1:8765' },
  },
})
