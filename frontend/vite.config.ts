import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

/** Where `npm run build` lands.
 *
 * The Python server mounts `research_team/interfaces/web/static` at `/static`
 * and serves `index.html` from its root, so building into that directory keeps
 * the backend's serving code untouched: the console is a separate application
 * with its own toolchain, and the only thing crossing the boundary is a
 * directory of built assets.
 */
const STATIC_DIR = fileURLToPath(new URL('../research_team/interfaces/web/static', import.meta.url))

/** The API server a `npm run dev` session talks to.
 *
 * Proxying rather than enabling CORS on the backend: the browser then sees one
 * origin in development exactly as it does in production, so nothing in the
 * application layer has to know which mode it is running under.
 */
const API_SERVER = process.env.RT_API_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  base: '/static/',
  resolve: {
    alias: {
      '@domain': fileURLToPath(new URL('./src/domain', import.meta.url)),
      '@application': fileURLToPath(new URL('./src/application', import.meta.url)),
      '@infrastructure': fileURLToPath(new URL('./src/infrastructure', import.meta.url)),
      '@presentation': fileURLToPath(new URL('./src/presentation', import.meta.url)),
      '@app': fileURLToPath(new URL('./src/app', import.meta.url)),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: API_SERVER,
        changeOrigin: true,
        // The event feed is an infinite response; without this the proxy
        // buffers it and no frame ever reaches the browser.
        ws: false,
      },
    },
  },
  build: {
    outDir: STATIC_DIR,
    emptyOutDir: true,
    // Off deliberately. This output is committed, so every frontend change
    // would otherwise add a two-megabyte map to the repository's history for a
    // debugging aid the dev server provides for free.
    sourcemap: false,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
