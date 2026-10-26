import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// /ask goes to the FastAPI backend (uv run uvicorn app.main:app --port 8000), so the browser needs no CORS setup
export default defineConfig({
  plugins: [svelte()],
  server: { proxy: { '/ask': 'http://localhost:8000', '/summary': 'http://localhost:8000' } },
})
