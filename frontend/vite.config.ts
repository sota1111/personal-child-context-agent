import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev, proxy /api to the local backend (uvicorn pcca.api.app:app --port 8080).
// In production the same-origin /api path is reverse-proxied by nginx to the backend
// Cloud Run service (see nginx.conf / start-nginx.sh), so the frontend never needs to
// know the backend URL and cookies stay first-party.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8080',
    },
  },
})
