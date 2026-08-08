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

/** Everything `react-force-graph-2d` pulls in, named for the `manualChunks`
 *  split below. Every one of these arrived with it -- see the commit that
 *  added the dependency -- so listing them is a snapshot of that install,
 *  not a maintenance burden that drifts on its own. */
const GRAPH_DEPENDENCIES = [
  'react-force-graph-2d',
  'react-kapsule',
  'force-graph',
  'kapsule',
  'accessor-fn',
  'bezier-js',
  'canvas-color-tracker',
  'float-tooltip',
  'index-array-by',
  'internmap',
  'jerrypick',
  'lodash-es',
  'loose-envify',
  'object-assign',
  'preact',
  'prop-types',
  // `react-is@17` also ships as a dev-only transitive of `@testing-library`;
  // this is the second, separately-resolved copy `prop-types` pulls in, and
  // the only one that reaches the built bundle at all.
  'react-is',
  'tinycolor2',
  '@tweenjs/tween.js',
  'd3-array',
  'd3-binarytree',
  'd3-color',
  'd3-dispatch',
  'd3-drag',
  'd3-ease',
  'd3-force-3d',
  'd3-format',
  'd3-interpolate',
  'd3-octree',
  'd3-quadtree',
  'd3-scale',
  'd3-scale-chromatic',
  'd3-selection',
  'd3-time',
  'd3-time-format',
  'd3-timer',
  'd3-transition',
  'd3-zoom',
]

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
    // Stated rather than inherited. Vite's default target moves with its
    // release cycle, and this output is committed: a toolchain upgrade should
    // not silently change the syntax level of a file already in the repository.
    // ES2022 is what `tsconfig.json` already type-checks against.
    target: 'es2022',
    rollupOptions: {
      output: {
        /** Why the bundle is split at all, given it is served from one origin
         *  and would load fine as a single file: the output is committed, so
         *  every chunk boundary is also a boundary in the repository's history.
         *  Unsplit, editing one component rewrites 460 kB of the diff. Split,
         *  a dependency-free change touches only `app-*.js`, and the vendor
         *  chunks change when — and only when — a dependency does.
         *
         *  The grouping follows how often each part moves, not what it does. */
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return 'react'
          if (/[\\/]node_modules[\\/](marked|dompurify|diff)[\\/]/.test(id)) return 'text'
          // Its own chunk, never folded into `vendor-`: `GraphCanvas` is the
          // only module that imports `react-force-graph-2d`, loaded with
          // `React.lazy`, so this chunk -- the library and everything it
          // pulls in, d3's force simulation included -- is fetched only by a
          // reader who opens the graph pane. Named explicitly rather than by
          // a `d3-*` pattern: none of these packages are pulled in by
          // anything else this project depends on today, and naming them
          // keeps a future unrelated dependency from silently landing here.
          if (GRAPH_DEPENDENCIES.some((pkg) => id.includes(`node_modules/${pkg}/`))) return 'graph'
          return 'vendor'
        },
        entryFileNames: 'assets/app-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
      },
    },
  },
  test: {
    globals: true,
    /** Two suites, because they need two different worlds. The application is
     *  tested in a DOM with the browser gaps stubbed; the build tooling reads
     *  config files off disk and needs a real Node, where `import.meta.url` is
     *  a file URL. Declaring that here beats a per-file docblock: the split is
     *  a property of the project, not of one test that happened to notice. */
    projects: [
      {
        extends: true,
        test: {
          name: 'app',
          environment: 'jsdom',
          setupFiles: ['./vitest.setup.ts'],
          include: ['src/**/*.test.{ts,tsx}'],
        },
      },
      {
        extends: true,
        test: {
          name: 'build',
          environment: 'node',
          include: ['scripts/**/*.test.ts'],
        },
      },
    ],
    coverage: {
      provider: 'v8',
      reporter: ['text-summary', 'lcov'],
      include: ['src/**/*.{ts,tsx}'],
      // Types carry no statements, the composition root is exercised by
      // running the application rather than by a unit test, and a `.test.ts`
      // file covering itself is not a measurement.
      exclude: ['src/**/*.test.{ts,tsx}', 'src/main.tsx', 'src/app/**', 'src/**/*.d.ts'],
      /** Ratchets, not targets. Each number sits just under what the suite
       *  actually reaches today, so the gate catches a *regression* — a layer
       *  that loses its tests, or a new module that arrives without any — and
       *  says nothing about work that has not been done yet.
       *
       *  They differ by layer on purpose, because a uniform number would be
       *  either a lie about the domain or an impossible bar for the views. The
       *  domain is where the rules live and is held near total; the
       *  presentation layer is thin, mostly-declarative, and covered in
       *  practice by driving the real application against the real server —
       *  which is why its floor is low rather than absent. Low and visible is
       *  the honest way to carry that debt. */
      thresholds: {
        lines: 42,
        functions: 31,
        branches: 33,
        statements: 42,
        'src/domain/**': { lines: 90, functions: 90, branches: 88, statements: 90 },
        'src/application/**': { lines: 66, functions: 46, branches: 50, statements: 60 },
        'src/infrastructure/**': { lines: 52, functions: 30, branches: 55, statements: 52 },
      },
    },
  },
})
