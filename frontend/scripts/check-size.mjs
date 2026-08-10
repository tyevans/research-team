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
  // 57, from 55: the landing page, rewritten around projects rather than
  // around the fork tree. Measured at 55.2 kB. What the 3.7 kB bought: each
  // project's sessions folded underneath it, all four routes reachable from a
  // project row, a live run marker, search, recency headings, per-region
  // empty/loading/error states, and a confirmation dialog that is the
  // console's own rather than the browser's. Roughly half of it is the two
  // things the page had none of -- state per region, and a project row with
  // more than a name on it.
  // 80, from 57, on the owner's instruction, and the reason is a priority
  // rather than a measurement: **bundle size is not what matters at this stage
  // of the product.** Exploring what the console should be is worth more right
  // now than keeping it small, and a gate with 0.6 kB of slack was firing on
  // ordinary feature work rather than on the thing it was written to catch.
  // The owner was explicit that this is not a rejection of the constraint --
  // the instinct to keep things tight still stands -- so this is a deliberate,
  // phase-specific loosening and should be revisited before release.
  //
  // Generous on purpose. Measured at 57.0 kB with the topic document viewer in
  // (the viewer itself cost 0.6 kB: a listing, a document body reusing
  // `useLesson`, and the stylesheet rules for both), and a floating
  // agent-status widget is landing in this same chunk next. A raise sized to
  // those two would be hit again immediately, which would not have done its
  // job. 23 kB of room is roughly a third again of everything our own code
  // currently ships.
  //
  // What is deliberately *kept*: the gate itself, and every note above and
  // below this one. The limits being loose does not make them pointless -- a
  // chunk that doubles overnight still trips this, which is the surprise worth
  // hearing about. And the per-chunk history records what each earlier
  // increase measured and bought, which stays useful reading even while nobody
  // is designing against the numbers.
  'app-': 80, // our code: every component, store, mapper and stylesheet rule
  'react-': 66, // react + react-dom + scheduler
  'text-': 34, // marked, dompurify, jsdiff — markdown and diff rendering
  // 48, from 38, on the same instruction and the same reasoning as `app-`.
  // Measured at 36.8 kB, which is 1.2 kB of slack -- close enough that one
  // ordinary dependency bump would trip it. This is the bucket a *new library*
  // lands in, so it is the one where the gate still has real work to do; 48
  // leaves it able to do that work without stopping exploratory changes that
  // add no dependency at all.
  'vendor-': 48, // query, zustand, wouter, zod, date-fns, clsx, @tanstack/react-virtual
  // The component system: `@radix-ui/*` and `class-variance-authority`. Its own
  // bucket rather than a raise to `vendor-`, so the one place a surprise
  // dependency still shows up keeps its 11 kB of slack and keeps biting.
  //
  // 56, measured at 0.0 kB, which needs explaining twice over.
  //
  // *Why it measures nothing:* phase 0 installs the toolchain and migrates no
  // component. CVA is a dependency that nothing imports yet, so it is not in
  // the bundle, and no Radix package is installed at all. The bucket is
  // declared empty on purpose -- a budget that arrives with the code it
  // budgets for is a budget nobody argued about, and this file exists because
  // that is the argument worth having.
  //
  // *Why 56 rather than 20:* the spec's phase table walks this bucket from
  // 16.6 kB (dialog) to 46.3 kB (twelve primitives) and proposes 52 as the
  // standing limit. Sizing to the first phase would mean editing this number
  // in four consecutive pull requests, and a limit that moves every time is a
  // limit nobody reads. The owner's instruction is that exploration outranks
  // bundle size at this stage, so this is deliberately generous: 56 is the
  // spec's end-state 52 plus room for the wrapper components' own variants,
  // and it is a tripwire rather than a squeeze. What it still catches is the
  // thing worth catching -- a primitive that costs 20 kB instead of 3, or a
  // second component library arriving beside the first.
  //
  // The honest cost, restated from §8.2 of the spec so it is not absorbed into
  // a number: at the end state this is ~46 kB gzipped, 19% of what the console
  // downloads today, spent entirely on interaction behaviour a user never sees
  // *added* -- no feature, no pixel. It is paid in instalments and it is
  // separately gated, which is what this line is for.
  'ui-': 56,
  'rolldown-runtime-': 2, // the bundler's own module loader, emitted once
  // react-force-graph-2d, force-graph, d3-force and the rest of what draws
  // the research page's graph pane -- see `GRAPH_DEPENDENCIES` in
  // `vite.config.ts` for the full list. Measured at 61.4 kB; `GraphCanvas-`
  // is the tiny wrapper chunk Rollup emits for the `React.lazy()` import
  // itself, which does not get the `graph-` prefix because it is app code,
  // not a dependency, and manualChunks only renames node_modules code.
  // 74, from 62, on the same instruction. Measured at 61.4 kB -- 0.6 kB of
  // slack, the tightest bucket here, and the graph pane is under active work.
  // Like `vendor-`, this is a dependency bucket rather than a first-party one,
  // so the raise is sized to stop it firing on pane changes while still
  // noticing a new graphing library.
  'graph-': 74,
  // Was 1 kB while this chunk was a bare `React.lazy` wrapper handing the
  // library a `graphData` prop. It now measures the container it is drawn in
  // and paints its own nodes -- a `ResizeObserver` that gives the canvas a
  // real width, and a canvas painter that draws each node's name and takes
  // its colour from the entity type. Both are what made the pane usable: the
  // canvas previously defaulted to `window.innerWidth` and drew itself off to
  // the side of the pane, and an unlabelled node gave a reader nothing to aim
  // at. Measured at 1.1 kB.
  'GraphCanvas-': 2,
  // 227 covered the research page's four panes; 228 added the links between
  // that page and the course page, and the breadcrumb that says which of the
  // two you are on. The last 2 kB is the research page's layout: a rail and a
  // stage in place of the four-pane grid, the floating search over the canvas,
  // this view's first media queries, and the node painting described above.
  // Measured at 228.6 kB, which is what tripped this gate.
  //
  // 231, from 230: filtering the topic queue. A search box, four counted
  // slices, and the domain predicate behind them -- half a kilobyte for the
  // difference between reading a project's queue and scrolling it.
  //
  // 232, from 231: the canvas legend, which is what made the node colours mean
  // anything, and the course page's autonomy disclosure. The graph search's
  // own answer-when-there-is-none fits inside the same raise.
  //
  // 236, from 232: the landing-page rewrite above, which is the whole of the
  // difference -- every other bucket measured the same before and after. 232
  // had 0.3 kB of headroom left, so this is the raise that was going to be
  // needed by whatever landed next; it is spent here on the one page the
  // owner said was hard to use.
  //
  // 512, from 236, on the owner's instruction. This one bought nothing: it is
  // headroom, not a change. Worth being clear about what it costs, since the
  // note above is the last one that will be forced for a long while. At 235.5
  // kB measured, this is 276 kB of slack -- more than the console currently
  // ships in total -- so `total` stops being a gate that anything realistic
  // will trip, and the per-chunk budgets above become the only real ones.
  // Those still bite, and are where a dependency would show up: a new library
  // lands in `vendor-` or `graph-`, and our own growth in `app-`. What is no
  // longer caught here is the shape this file was written for -- several
  // chunks each growing within their own limit while the page a reader
  // actually downloads doubles. If that matters again, the number to move is
  // this one.
  total: 512,
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
