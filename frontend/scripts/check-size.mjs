#!/usr/bin/env node
/**
 * The bundle budget.
 *
 * A dependency never announces that it cost 300 kB; it announces that it solved
 * a problem, and the cost shows up months later as a console that takes a
 * second to paint. This is the gate that makes the cost arrive at the same time
 * as the decision — a pull request that crosses a limit fails here, and either
 * the limit moves on purpose or the dependency does not land.
 *
 * Sizes are gzipped. Note that this repository's own server does not compress
 * — adding `GZipMiddleware` would sit in front of the SSE feed too, and a
 * buffered event stream is a worse bug than a large download. Gzip is still the
 * right unit here: it is what any real deployment puts in front of this, and it
 * is the measure that tracks *content* rather than how verbose the minifier felt.
 *
 * Raising a limit is a legitimate change. Raising it in the same commit that
 * consumed it, with no note about what was bought, is the thing this catches.
 */
import { gzipSync } from 'node:zlib'
import { readFile, readdir } from 'node:fs/promises'
import { fileURLToPath, URL } from 'node:url'
import path from 'node:path'

const ASSETS = fileURLToPath(
  new URL('../../research_team/interfaces/web/static/assets', import.meta.url),
)

/** Gzipped kilobytes. Keyed by the chunk-name prefix Rollup emits. */
const BUDGET_KB = {
  'app-': 55, // our code: every component, store, mapper and stylesheet rule
  'react-': 66, // react + react-dom + scheduler
  'text-': 34, // marked, dompurify, jsdiff — markdown and diff rendering
  'vendor-': 38, // query, zustand, wouter, zod, date-fns, clsx, @tanstack/react-virtual
  'rolldown-runtime-': 2, // the bundler's own module loader, emitted once
  // react-force-graph-2d, force-graph, d3-force and the rest of what draws
  // the research page's graph pane -- see `GRAPH_DEPENDENCIES` in
  // `vite.config.ts` for the full list. Measured at 61.4 kB; `GraphCanvas-`
  // is the tiny wrapper chunk Rollup emits for the `React.lazy()` import
  // itself, which does not get the `graph-` prefix because it is app code,
  // not a dependency, and manualChunks only renames node_modules code.
  'graph-': 62,
  'GraphCanvas-': 1,
  // 227 covered the research page's four panes; the last 1 kB is the links
  // between that page and the course page, and the breadcrumb that says which
  // of the two you are on. Measured at 227.1 kB, which is what tripped this
  // gate -- the cross-links were the change that consumed the headroom.
  total: 228,
}

const kb = (bytes) => Math.round((bytes / 1024) * 10) / 10

const bucketFor = (name) =>
  Object.keys(BUDGET_KB).find((prefix) => prefix !== 'total' && name.startsWith(prefix))

const files = await readdir(ASSETS).catch(() => {
  console.error(`No build found at ${ASSETS}. Run \`npm run build\` first.`)
  process.exit(1)
})

const measured = await Promise.all(
  files
    .filter((name) => name.endsWith('.js') || name.endsWith('.css'))
    .map(async (name) => ({
      name,
      gzip: gzipSync(await readFile(path.join(ASSETS, name))).length,
    })),
)

// CSS rides with the entry chunk as far as a reader is concerned: it is our
// code, it changes when our code changes, and it is fetched on the same paint.
const charged = measured.map((file) => ({
  ...file,
  bucket: file.name.endsWith('.css') ? 'app-' : bucketFor(file.name),
}))

const spent = new Map()
for (const file of charged) {
  if (file.bucket) spent.set(file.bucket, (spent.get(file.bucket) ?? 0) + file.gzip)
}
const total = charged.reduce((sum, file) => sum + file.gzip, 0)

const failures = []
for (const [bucket, limit] of Object.entries(BUDGET_KB)) {
  const used = bucket === 'total' ? total : (spent.get(bucket) ?? 0)
  const line = `${bucket.padEnd(18)} ${String(kb(used)).padStart(7)} kB  of ${limit} kB`
  if (kb(used) > limit) failures.push(line)
  console.log(`${kb(used) > limit ? '✗' : '·'} ${line}`)
}

// A chunk nobody budgeted for is not free — it is a chunk whose growth nothing
// is watching. Naming a new bucket is a two-line change; silence is not.
const unbudgeted = charged.filter((file) => !file.bucket)
for (const file of unbudgeted) {
  failures.push(`${file.name} (${kb(file.gzip)} kB) has no entry in BUDGET_KB`)
  console.log(`✗ ${file.name} is not covered by any budget`)
}

if (failures.length) {
  console.error(`\nOver budget:\n  ${failures.join('\n  ')}`)
  console.error(
    '\nEither trim the change, or raise the limit in scripts/check-size.mjs and say what it bought.',
  )
  process.exit(1)
}
console.log(`\nWithin budget — ${kb(total)} kB gzipped across ${charged.length} files.`)
