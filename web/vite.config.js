import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync } from 'node:fs'

// Dev server. `/api/*` is proxied to the backend so `VITE_API_BASE=/api`
// (the same-origin model used in the container behind nginx) works during
// `npm run dev` too. Point the proxy elsewhere with VITE_DEV_API_PROXY.
// With no VITE_API_BASE set, client.js talks to http://localhost:8000
// directly and this proxy is simply unused.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_DEV_API_PROXY || 'http://localhost:8000'
  // Shown above Sign out in the sidebar. Version is package.json's; the build
  // number is the UTC build time (YYYYMMDD.HHMM) unless CI sets BUILD_NUMBER --
  // a Docker build has no git history to derive one from.
  const version = JSON.parse(readFileSync('./package.json', 'utf8')).version
  const build = process.env.BUILD_NUMBER
    || new Date().toISOString().slice(0, 16).replace(/[-:]/g, '').replace('T', '.')
  return {
    define: {
      'import.meta.env.VITE_APP_VERSION': JSON.stringify(version),
      'import.meta.env.VITE_APP_BUILD': JSON.stringify(build),
    },
    plugins: [
      react(),
      tailwindcss(),
    ],
    test: { environment: 'jsdom', globals: false, restoreMocks: true },
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/api': { target, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') },
      },
    },
  }
})
