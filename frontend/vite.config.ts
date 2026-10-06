import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

// `npm run dev` serves the UI on :5180 and sends everything else to the stack
// (docker compose -f deploy/docker-compose.yml up -d). Sign-in then returns to
// the stack's own address, so for signed-in work open http://localhost:8090.
const stack = process.env.TWIN_STACK ?? 'http://localhost:8090'
// the gateway refuses changes from pages of another origin, and this page is on :5180
const api = {
  target: stack,
  configure: (proxy: { on: (e: 'proxyReq', f: (req: { getHeader: (h: string) => unknown; setHeader: (h: string, v: string) => void }) => void) => void }) =>
    proxy.on('proxyReq', req => { if (req.getHeader('origin')) req.setHeader('origin', new URL(stack).origin) }),
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    // `^/s/`: a link for viewing (a plain '/s' would catch /src as well)
    proxy: { '/api': api, '/auth': stack, '/kc': stack, '^/s/': stack },
  },
})
