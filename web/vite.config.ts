import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// при разработке сервер — `uv run python -m app serve --port 8010` (server/README.md)
const api = process.env.API_URL ?? "http://localhost:8010";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
  server: {
    proxy: { "/api": { target: api, ws: true, changeOrigin: false } },
  },
  build: { chunkSizeWarningLimit: 1500 },
});
