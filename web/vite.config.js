import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev server. `/api/*` is proxied to the backend so `VITE_API_BASE=/api`
// (the same-origin model used in the container behind nginx) works during
// `npm run dev` too. Point the proxy elsewhere with VITE_DEV_API_PROXY.
// With no VITE_API_BASE set, client.js talks to http://localhost:8000
// directly and this proxy is simply unused.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_DEV_API_PROXY || 'http://localhost:8000'
  return {
    plugins: [
      react(),
      tailwindcss(),
      {
        // Mirror nginx: "/" is the landing page, the SPA login is /login.
        name: 'landing-at-root',
        configureServer(server) {
          server.middlewares.use((req, _res, next) => {
            if (req.url === '/' || req.url.startsWith('/?')) req.url = '/welcome.html'
            next()
          })
        },
      },
    ],
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/api': { target, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') },
      },
    },
  }
})
