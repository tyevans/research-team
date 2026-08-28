import { fileURLToPath, URL } from 'node:url'

import { playwright } from '@vitest/browser-playwright'
import tailwindcss from '@tailwindcss/vite'
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
  /** Tailwind is a Vite plugin rather than a PostCSS step: v4's own guidance,
   *  and it is the only integration that gets incremental rebuilds in `dev`.
   *  It scans source files for class names and emits only the utilities it
   *  finds, so with no component yet using one it contributes essentially
   *  nothing to the bundle -- measured at +0.1 kB gzipped on `app-` in the
   *  commit that added it, which is the theme variables and nothing else. */
  plugins: [tailwindcss(), react()],
  base: '/static/',
  resolve: {
    /* One React, however a module got here. Added for the browser suite and
       stated rather than left to look like hygiene: in browser mode Vite
       pre-bundles `@tanstack/react-query` into its own optimised chunk, that
       chunk resolved a second copy of React, and any test mounting a component
       under `QueryClientProvider` died on "Invalid hook call" before rendering
       anything -- `AgentWidget.browser.test.tsx` is the one that hit it. The
       jsdom suite never saw it, because it does not pre-bundle the same way.
       Costs nothing in the application build, where there is one copy already;
       what it buys is that the browser suite can mount a real container-backed
       component instead of a hand-written imitation of its markup. */
    dedupe: ['react', 'react-dom'],
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
          // The component system's own bucket, carved out exactly as `graph-`
          // was. The alternative was to let Radix land in `vendor-` and raise
          // that limit, which works and destroys the bucket: `vendor-` is
          // where a *new library* shows up, so it is the one place the gate
          // still has real work to do, and giving it 40 kB of migration-shaped
          // slack is the same as removing it.
          //
          // Declared in phase 0, before anything lands in it, so the budget
          // exists at the moment the first Radix import is written rather than
          // being added by the commit that needs it — which is the shape of
          // raise this file was written to catch. Today it measures 0.0 kB:
          // `class-variance-authority` is installed but not yet imported by
          // any component, and an unimported dependency is not in the bundle.
          if (id.includes('node_modules/@radix-ui/')) return 'ui'
          if (id.includes('node_modules/class-variance-authority/')) return 'ui'
          return 'vendor'
        },
        /** No `[hash]`, which is not the usual choice and is worth the
         *  paragraph.
         *
         *  A content hash in the filename makes every rebuild a *rename*, and
         *  this output is committed. Git detects the rename on both sides of a
         *  merge -- a rebuilt chunk is ~99% identical to the one it replaces,
         *  well past the similarity threshold -- and reports
         *  `CONFLICT (rename/rename): app-AAA.js renamed to app-BBB.js in HEAD
         *  and to app-CCC.js in <branch>` for every chunk, on top of a content
         *  conflict in `index.html`. That happens whether or not the two
         *  branches' *source* changes overlap at all, because the hash of a
         *  bundle is a function of the whole bundle. Measured on #157 stacked
         *  on #156: six conflicts, three of them purely this, none of them a
         *  real disagreement. 89 of this repository's 297 commits carry build
         *  output, so it is not rare.
         *
         *  Stable names turned that into an ordinary same-path content
         *  conflict, which a `merge=ours` driver could dispose of. That whole
         *  argument expired on 2026-08-18, when the build output stopped being
         *  committed at all (`.gitignore` carries why) and the driver and its
         *  `.gitattributes` went with it. The hash stays off anyway, for the
         *  reason below: this server sends `no-cache` rather than
         *  far-future-immutable, so a hash buys nothing here and a stable name
         *  keeps `npm run dev` and the built console naming the same files.
         *
         *  What the hash cost us to give up: cache-busting. Less than it
         *  sounds, because this server was never taking the payoff. `StaticFiles`
         *  sends `ETag` and `Last-Modified` and *no* `Cache-Control` (verified
         *  against the installed starlette), so nothing here was being cached
         *  far-future-immutable the way hashed assets normally are. The one
         *  real exposure is heuristic freshness -- a browser may reuse a
         *  long-unmodified file without revalidating, and a stable name means
         *  the reuse is of the wrong bytes rather than of a file that no longer
         *  exists. `app.py`'s static mount now sends `Cache-Control: no-cache`
         *  to close exactly that window; the two changes only make sense
         *  together, and separating them reintroduces the bug.
         *
         *  What a test would fail on: `scripts/check-size.mjs` buckets by
         *  filename, and its keys are these names. */
        entryFileNames: 'assets/app.js',
        chunkFileNames: 'assets/[name].js',
        // Vite's default is `assets/[name]-[hash][extname]`, which would leave
        // the stylesheet as the one hashed file and so the one file still
        // renaming on every build -- the whole problem, at 1/9th scale.
        assetFileNames: 'assets/[name][extname]',
      },
    },
  },
  test: {
    globals: true,
    /** Three suites, because they need three different worlds. The application
     *  is tested in a DOM with the browser gaps stubbed; the build tooling reads
     *  config files off disk and needs a real Node, where `import.meta.url` is
     *  a file URL; and a handful of claims need a real engine that lays out and
     *  applies a stylesheet. Declaring that here beats a per-file docblock: the
     *  split is a property of the project, not of one test that happened to
     *  notice. */
    projects: [
      {
        extends: true,
        test: {
          name: 'app',
          environment: 'jsdom',
          setupFiles: ['./vitest.setup.ts'],
          include: ['src/**/*.test.{ts,tsx}'],
          // `*.test.tsx` would otherwise match `*.browser.test.tsx` too, and
          // those files assert on geometry and computed styles -- every one of
          // them fails under jsdom, which is the entire reason they exist.
          exclude: ['src/**/*.browser.test.tsx'],
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
      {
        extends: true,
        test: {
          /** The claims jsdom cannot judge, in an engine that can.
           *
           * jsdom lays nothing out and applies no stylesheet: `scrollHeight` is
           * 0 on every element, `getComputedStyle` returns what the inline
           * style says and nothing a rule contributed, and a selector that
           * matches nothing is indistinguishable from one that matches. Four
           * findings in a row have had their real assertion written as a
           * comment for that reason, and one of them -- a chosen control
           * drawing in the unchosen colour, because two Radix components wrote
           * to the same `data-state` -- shipped past a fully green suite.
           *
           * **Not in `npm run verify`, deliberately, so not in CI.** The four
           * gates are unchanged and this is a fifth thing you run: `npm run
           * test:browser`. The cost is real and is the reason it is worth
           * naming rather than discovering -- a suite nobody is forced to run
           * is a suite that rots, and this one will be wrong the first time
           * somebody changes a stylesheet without running it. It is here on the
           * bet that a cheap local check beats a comment, and it earns a CI job
           * the day it has caught something on its own.
           *
           * Headless Chromium via Playwright, one browser rather than three:
           * these assertions are about whether *a* real engine agrees, not
           * about cross-browser difference, and this console has one user on
           * one machine. */
          name: 'browser',
          include: ['src/**/*.browser.test.tsx'],
          // A different setup file, not this suite's. `vitest.setup.browser.ts`
          // argues why at length; the short version is that the jsdom setup
          // pins `offsetWidth`/`offsetHeight` to constants.
          setupFiles: ['./vitest.setup.browser.ts'],
          browser: {
            enabled: true,
            provider: playwright(),
            headless: true,
            // Vitest's own `page` proxy has no `emulateMedia` -- it forwards only
            // the commands the framework has chosen to wrap, and this is not one
            // of them (`a11y.browser.test.tsx` records the same gap: "the sweep's
            // browser reports no such preference", with no fix beside it). The
            // real Playwright `Page` does have `emulateMedia`, and the playwright
            // provider hands it to a custom command's context -- this is the one
            // channel between a test file and that object, so a `prefers-reduced-
            // motion` assertion has to go through it rather than through `page`.
            commands: {
              async setReducedMotion(context, reduced: boolean) {
                await context.page.emulateMedia({
                  reducedMotion: reduced ? 'reduce' : 'no-preference',
                })
              },
            },
            // Stated, because the layout rules this suite exists to check are
            // media queries and a media query reads the *viewport* -- not the
            // width of whatever wrapper a test renders into. The first run of
            // `layout.browser.test.tsx` failed on exactly that: a `Split` inside
            // a 1200px div reported a horizontal collapsed title, correctly,
            // because the default viewport is below `--bp-narrow` and the panes
            // had stopped being columns. 1440x900 is the width every finding so
            // far was measured at by hand.
            viewport: { width: 1440, height: 900 },
            instances: [{ browser: 'chromium' }],
          },
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
      //
      // Stories are excluded for a sharper reason than "they are not
      // production code". They live in `src/` and would otherwise be counted
      // as it: dozens of small modules, every line of them executed the moment
      // a test composes one, which inflates every ratchet below. The
      // thresholds are explicitly "just under what the suite actually reaches
      // today", so a wave of trivially-covered files does not raise the floor
      // — it stops the floor from measuring anything. This exclusion has to
      // land in the same commit as the first story or the gate is already
      // wrong; it did.
      exclude: [
        'src/**/*.test.{ts,tsx}',
        'src/**/*.stories.tsx',
        'src/main.tsx',
        'src/app/**',
        'src/**/*.d.ts',
        // Test helpers, for the same reason as the tests that import them: a
        // module whose only caller is a test file is not application code, and
        // `src/test/browser-viewport.ts` is reached *only* by the browser
        // suite — which runs outside `verify` and collects no coverage. Left
        // in, it would be counted as permanently-uncovered application lines
        // and would push every ratchet below down by whatever it happened to
        // weigh.
        'src/test/**',
      ],
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
