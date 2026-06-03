import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Read at config-load time so docker compose can point the dev server at the
// `api` service inside the docker network. Local `npm run dev` keeps the
// localhost default.
const apiTarget = process.env.API_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    clearMocks: true,
  },
})
