import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

// `npm run dev` serves the UI on :5180 and sends everything else to the stack
// (docker compose -f deploy/docker-compose.yml up -d). Sign-in then returns to
// the stack's own address, so for signed-in work open http://localhost:8090.
const stack = process.env.TWIN_STACK ?? 'http://localhost:8090'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    proxy: { '/api': stack, '/auth': stack, '/kc': stack },
  },
})
