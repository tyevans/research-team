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

/** Gzipped kilobytes. Keyed by the exact chunk name Rollup emits, which since
 *  the build stopped hashing filenames is also the name on disk minus its
 *  extension -- see `entryFileNames` in `vite.config.ts` for why there is no
 *  hash. These keys and that config are two halves of one fact: rename a chunk
 *  there and this gate reports it as unbudgeted rather than silently stopping
 *  measuring it, which is the failure this arrangement is chosen to produce. */
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
  //
  // 80 -> 84: perception reaching the console. Measured at 80.1 kB, which is
  // what tripped this gate. (An earlier draft of this note blamed the
  // remaining slack on "media perception's backend landing", which is not a
  // thing that can happen -- no Python change moves the `app` chunk. What
  // consumed the 80 raise's room was ordinary frontend work across the
  // intervening features, and this note does not identify which; the honest
  // statement is the measurement.) What the 0.3 kB bought: a Transcribe control
  // on a medium nothing has been derived from, the link to the transcript on
  // one that has, the degradations line under a derived source, the perceive
  // mutation and its repository call, and the join between a medium and its
  // transcript that the wire cannot carry (`derived_from` is on the text arm).
  // Deliberately no player, no cue list and no seeking -- those need a locator
  // syntax another sub-project owns, and half of one built here would be built
  // twice.
  //
  // 80 -> 96: the ontology layer -- the fold, the classes view, the repository
  // and a ninth tab -- measured at 81.3 kB against a limit already at 80.1
  // before any of it landed, so that raise cleared a pre-existing overage too.
  //
  // Those two happened on separate branches and each raised the same 80,
  // which is how they conflicted. **Neither measurement describes this
  // tree**: 80.1 and 81.3 were each taken with the other feature absent, so
  // both understate the merged chunk, and adding the deltas would be a guess
  // rather than a reading. 96 is kept -- the higher of the two, not their sum
  // -- and re-measured after the merge at the figure recorded below. The
  // reason to prefer the higher number over a tighter one is the same in both
  // notes and is the owner's standing position: exploration outranks bundle
  // size at this stage, and a limit set a kilobyte above the measurement is a
  // limit the next feature trips. The last four raises here were each provoked
  // by a feature rather than chosen. ~14 kB of headroom is roughly four
  // features the size of these, which is enough to stop the number moving
  // every slice while still catching the thing worth catching -- a chunk that
  // doubles overnight. A deferral with a date on it, revisited before release
  // along with every other number in this file.
  //
  // Merged and re-measured on 2026-08-16: **81.7 kB** -- which is under 84,
  // so the lower of the two conflicting numbers would in fact have held. The
  // deltas were 1.2 and 0.3 kB and they did not compound. 96 is kept anyway,
  // on the standing position above rather than on necessity, and this line
  // says so plainly so nobody later reads 96 as a number the measurement
  // demanded.
  //
  // 96 -> 104: the curriculum layer -- the area map, the path steps, the area
  // detail, the authoring bar, the repository, the DTOs and mappers, and a
  // tenth tab. **Measured at 97.0 kB against 96**, so the raise is 7 kB of
  // headroom over a 1.0 kB overage rather than a number the measurement
  // demanded, and this line says so for the reason the note above says the
  // same of 96.
  //
  // What the 1 kB bought: a project's knowledge graph folded into learning
  // areas and an ordered path, both readable in the console, with the
  // evidence for every ordering claim on screen beside it.
  //
  // Nothing here is lazy, deliberately. The two lazy chunks in this build are
  // canvases over ~60 kB of third-party drawing code; this is a few kB of
  // ordinary components with no dependency of their own, and a chunk boundary
  // around it would buy a fraction of a kilobyte on the default tab in
  // exchange for a suspense boundary and a second network round trip on the
  // tab a reader actually opened.
  // 104 -> 112: the course page stopped being a wall. Two changes crossed
  // the line within 0.4 kB of each other -- the cluster's membership folded
  // into a grouped, filterable disclosure (**measured at 104.4 kB against
  // 104**) and the course's widgets started rendering through
  // `LessonDocument` rather than printing their yaml (**measured at 104.1
  // kB**). Neither is a number the measurement demanded: the overages are
  // 0.4 and 0.1 kB, and 112 is 8 kB of headroom taken deliberately, on the
  // standing position the notes above state, so that the next few components
  // on this page do not each raise this line by a kilobyte.
  //
  // What the 0.5 kB bought: a realized course you can actually take -- 19
  // interactive widgets on the reference course where there had been 19
  // blocks of raw yaml, and 66 cluster members that fold away instead of
  // burying the course under themselves.
  // 115, from 112, for the root `ErrorBoundary`: a fallback surface with a
  // message, a component stack and three recovery controls, plus the
  // stylesheet rules it needs. The measured cost is 0.9 kB gzipped and the
  // headroom is the usual half-kilobyte. What it buys is the difference
  // between a render throw showing a white screen with the error only in
  // devtools and one showing the error with three ways out -- which is
  // exactly the trade this budget is meant to be argued in front of, rather
  // than shaving the fallback down to an apology to stay under a number.
  //
  // 115 -> 124: the lesson slideshow.
  //
  // **Measured twice, because only one of the two numbers is this change's.**
  // On 2026-08-29 at `f5a98462`, in one worktree, built twice: with the deck
  // reachable, **116.2 kB**; with the single `Deck` import removed from
  // `CourseFile` so the whole surface shakes out, **112.9 kB**. So the deck
  // costs **3.3 kB**.
  //
  // Both were taken before the `ErrorBoundary` raise above existed on this
  // branch, so 112.9 is a base that predates it and the two are not additive in
  // any way this note can claim -- the honest reading is that the deck adds 3.3
  // kB to whatever the merged tree measures, and nobody has re-measured the
  // merge. An earlier draft of this paragraph read 112.9 as "the base was
  // already 0.9 kB over" and filed it as somebody else's overage; the rebase
  // showed it was the `ErrorBoundary`, landing on `main` with its own raise.
  // Kept as a correction rather than deleted, because the wrong reading is the
  // one a future measurement here is most likely to repeat.
  //
  // 124 is ~8 kB of headroom over the last figure taken, on the standing
  // position the notes above state rather than on necessity.
  //
  // What the 3.3 kB bought: every lesson this system has ever authored gained a
  // second reading -- a keyboard-driven, deep-linkable deck with the widgets
  // still live on the slide -- from a pure segmenter over the parse that was
  // already on the wire. No new dependency, no new stylesheet, no new event, and
  // nothing added to the payload.
  // 112 -> 120: the index redesigned as a project board, raised concurrently
  // with the two above and **kept as history rather than as the live number**.
  //
  // **The interesting measurement was the baseline, not the delta.** Before
  // any of today's three raises, `main` measured **112.0 kB against 112** --
  // exactly on the line with no slack at all, so the next frontend change of
  // any size was going to trip this gate whatever it was. The board measured
  // **112.4 kB**, a 0.4 kB delta, and was merely one of the changes that
  // arrived first. Measured by building the parent commit with the branch's
  // own files removed rather than by subtracting -- an orphaned module is
  // tree-shaken but a restored one is not, and the first attempt read 112.3
  // because four of the branch's files were still on disk.
  //
  // What the 0.4 kB bought, net of a large deletion: the index stopped being
  // six identical rows. `ProjectCard`, `ProjectList`, `ProjectRows`, the
  // `useProjectActivity` hook, four `landing.ts` exports and a whole
  // stylesheet came *out* -- 2,750 deleted lines against 1,924 added -- and
  // what went in is a board drawing each project's position in the pipeline:
  // three peer-scaled tracks, a two-tone corpus bar whose amber tail is
  // ingest extraction has not caught up with, a sort control, and a first-run
  // page that teaches the four stages. The redesign very nearly paid for
  // itself in bytes, which is why the delta is 0.4 rather than the ~1 kB the
  // last four features each cost.
  //
  // **Three branches raised the same 112 within hours -- the 80 -> 84 /
  // 80 -> 96 collision again, with one more arm.** The error boundary
  // measured 112.9, the board 112.4, and the deck 116.2, each taken with the
  // other two absent. **None of those three describes this tree**, and adding
  // the deltas would be a guess rather than a reading. So the rule the older
  // note set is followed: keep the highest, never the sum. 124 stands.
  //
  // Rebased onto all three and re-measured on 2026-08-29: **117.3 kB**. That
  // is the first number in this paragraph taken against a tree that holds all
  // of them, and it is what the ~7 kB of headroom above is headroom over.
  //
  // **They very nearly did compound this time, and that is worth recording
  // because the older note says the opposite happened before.** 112.0 plus
  // the three deltas (0.9 + 0.4 + 3.3) predicts 116.6 against a measured
  // 117.3. So the sum was a decent estimate here where it was a bad one for
  // the 80 -> 84 / 80 -> 96 pair, whose deltas did not compound at all. The
  // rule that survives both is not "deltas compound" or "deltas don't" -- it
  // is that you cannot know which without building the merged tree, so keep
  // the highest and re-measure.
  //
  // W-A's identity foundation -- a login screen, an account menu, an auth
  // repository with two zod schemas, and two query hooks -- lands on top of
  // all four and **does not move this line**. Measured on the merged tree
  // rather than estimated, which is the rule the paragraph above arrives at:
  // 118.6 kB against the 117.3 above, so 1.3 kB. It fits inside the
  // headroom the deck's raise already took, so raising again would be taking
  // headroom over headroom.
  // 125, from 124, for B158's markdown unification -- the rules that dress
  // rendered prose. Measured rather than estimated, both sides on this tree on
  // 2026-08-29: `main`'s four stylesheets in place read 123.9 kB, and this
  // branch's read 124.1. So the change is **0.2 kB gzipped** and the raise is
  // 0.9 kB, of which 0.7 is the slack `main` was already down to.
  //
  // What it buys, which is the only reason to take a raise this small rather
  // than shave: every heading, paragraph, list, quotation, table and code span
  // on the eleven surfaces that render model prose had been drawing on the
  // browser's own defaults since 2026-08-07, because `markdown.css` styled nine
  // class families `marked` does not emit. 0.2 kB is the entire cost of them
  // being dressed at all.
  //
  // Worth knowing before the next raise: `main` had **0.1 kB** of headroom here
  // when this was measured, which is not a budget doing any work -- it is a
  // budget that stops whichever branch arrives next, on the merits of nothing.
  // W-C1's provider slice is raising this line to 132 on its own measurement,
  // and this edit will conflict with that. That is the intended outcome per
  // CLAUDE.md's merge-invisible-pair section: two branches rewriting one line
  // is a conflict a person resolves, rather than two silent raises.
  // 128, from 125, for the settings page's connection test: a `ConnectionTest`
  // component, the `CONNECTIONS` registry, the provider/probe DTOs and their
  // zod schemas, and the datalist of models a probe returns. Measured on this
  // tree on 2026-08-29 rather than estimated: **125.2 kB**, against a 125
  // budget `main` had already spent down to 0.1 kB of headroom. So the raise
  // is 2.8 kB for a 0.2 kB change, and the extra is deliberate -- a budget
  // sitting 0.2 kB above the measurement stops the next branch on the merits
  // of nothing, which is what the note above says happened here twice.
  //
  // What it buys: the only way to find a bad endpoint was to start a run and
  // read the error out of a failed turn. The routes to ask directly have
  // existed since the settings feature shipped and nothing called them.
  app: 128, // our code: every component, store, mapper and stylesheet rule
  react: 66, // react + react-dom + scheduler
  text: 34, // marked, dompurify, jsdiff — markdown and diff rendering
  // 48, from 38, on the same instruction and the same reasoning as `app-`.
  // Measured at 36.8 kB, which is 1.2 kB of slack -- close enough that one
  // ordinary dependency bump would trip it. This is the bucket a *new library*
  // lands in, so it is the one where the gate still has real work to do; 48
  // leaves it able to do that work without stopping exploratory changes that
  // add no dependency at all.
  vendor: 48, // query, zustand, wouter, zod, date-fns, clsx, @tanstack/react-virtual
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
  ui: 56,
  'rolldown-runtime': 2, // the bundler's own module loader, emitted once
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
  graph: 74,
  // Was 1 kB while this chunk was a bare `React.lazy` wrapper handing the
  // library a `graphData` prop. It now measures the container it is drawn in
  // and paints its own nodes -- a `ResizeObserver` that gives the canvas a
  // real width, and a canvas painter that draws each node's name and takes
  // its colour from the entity type. Both are what made the pane usable: the
  // canvas previously defaulted to `window.innerWidth` and drew itself off to
  // the side of the pane, and an unlabelled node gave a reader nothing to aim
  // at. Measured at 1.1 kB.
  GraphCanvas: 2,
  // The timeline pane's `React.lazy` wrapper, same shape as `GraphCanvas`
  // above: a hand-rolled SVG drawing, kept out of the main chunk so no page
  // without a Timeline tab pays for it. No dependency behind it -- it draws
  // with plain SVG rather than a charting library -- so its budget is sized
  // like GraphCanvas's own wrapper chunk rather than the graph pane's
  // dependency bucket. Measured at 1.2 kB gzipped.
  TimelineCanvas: 2,
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

// Exact, on the basename, now that the emitted names carry no hash to skip
// past. `startsWith` was what a hashed `app-Bjl3iwJ5.js` required, and it is
// strictly worse here: it would let a future `append.js` be silently charged to
// `app`'s budget and so escape the "no chunk goes unbudgeted" check below,
// which is the one thing this file cannot afford to get wrong quietly.
const bucketFor = (name) => {
  const stem = name.replace(/\.(js|css)$/, '')
  return Object.keys(BUDGET_KB).find((bucket) => bucket !== 'total' && bucket === stem)
}

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
  bucket: file.name.endsWith('.css') ? 'app' : bucketFor(file.name),
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
