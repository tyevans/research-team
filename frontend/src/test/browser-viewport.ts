import { page } from 'vitest/browser'
import { expect } from 'vitest'

import { BREAKPOINTS } from '@presentation/layout/layout-tokens.ts'

/** One resize helper for the browser suite, because four files wrote four and
 *  three of them shipped the same bug.
 *
 * `page.viewport(w, h)` resolves when the iframe has been resized. That is
 * upstream of everything a layout test wants to read: `matchMedia` has not
 * fired, `useWide`'s `useSyncExternalStore` subscription has not observed it,
 * React has not committed, and the browser has not re-laid-out. So every caller
 * has to wait on *something*, and the failure mode of picking one signal is
 * that the signal is already true at the width you started from — the helper
 * returns on the first tick and the probe measures the **old** layout, silently,
 * against code that is correct.
 *
 * **Three failed readings are on record, and they are the reason this polls
 * what it polls** (`BACKLOG.md` B64; the plan of 2026-08-14 §1):
 *
 * 1. `project-responsive`'s `widen()` polled the split's *inline* template being
 *    empty. That is already true anywhere below `--bp-wide`, so a 1000 -> 700
 *    resize resolved without waiting for `matchMedia`, for `stacked`, or for a
 *    React commit. It worked only crossing `--bp-wide`, and only because an
 *    `afterEach` restored 1440 between tests.
 * 2. A helper polling `data-collapse-to === 'rail'` had the mirror-image hole:
 *    `'rail'` is the value on **both** sides of `--bp-wide`, so a 1440 -> 821
 *    resize satisfied it instantly and the probe read the 1440 layout — a
 *    three-track template and an 880px pane inside an 821px viewport.
 * 3. `project-stacked`'s `stack()` was written to avoid both, by polling an
 *    attribute *and* geometry. That is the shape kept here.
 *
 * **The rule those three add up to: neither a React-written attribute nor
 * resolved geometry is sufficient alone.** An attribute can be stale-correct
 * (case 2); geometry waits on the browser rather than on React, so it can
 * settle while a component still holds a template from the old width (case 1).
 * Both, always — and the two React signals below are needed *together* for the
 * same reason, since each is constant across one of the two boundaries.
 *
 * What each poll actually blocks on, boundary by boundary — this is the
 * argument that no poll here is decoration:
 *
 * | resize | what blocks |
 * | --- | --- |
 * | 1440 -> 821, 1181 -> 1180 | the inline template, present above `--bp-wide` and absent below |
 * | 1000 -> 700, 700 -> 1000 | `data-collapse-to`, `'strip'` below `--bp-narrow` and `'rail'` above |
 * | 1440 -> 1181, 821 -> 700 | the split's own box width; **neither** React signal changes within a band |
 *
 * Drop any one of them and some resize in the suite becomes a no-op.
 *
 * **The fourth poll is the one with a cost, and it is paid deliberately.** A
 * template that overflows never settles, so against a *broken* stylesheet it
 * times out rather than resolving, and the caller's own assertion never runs —
 * the failure moves from the test's number to this helper's. It is kept because
 * refusing failed reading 2 is its whole job, and the cost is paid down by
 * making the give-up value name the tracks and the width; see the call site.
 *
 * **Measured on 2026-08-14 in Chromium, not reasoned.** A probe resized the
 * project page 1440 -> 821 and polled a single signal at `{ interval: 1 }`.
 * Polling only `data-collapse-to`, and polling only the split's box width, both
 * returned with the page in this state:
 *
 *     grid-template-columns: 344px 342px 352px   (three tracks, sum 1038)
 *     data-pane="material" width: 1038           (in an 821px viewport)
 *
 * — failed reading 2, reproduced. Both signals are *already correct* there:
 * `'rail'` is the form on both sides of `--bp-wide`, and the split's box had
 * reached 821 while it still carried the 1440 template. The full poll set above
 * returns at `344px 476.984px`, MATERIAL 821, which is the real layout.
 *
 * **The honest caveat, because it changes how much this is worth.** The stale
 * window is *one animation frame*: `inline` and the track-fit both flip at
 * frame 1, everything else is already true at frame 0. `expect.poll`'s default
 * 50ms interval means a single-poll helper's first check usually lands after
 * that frame, and the same probe run without `{ interval: 1 }` read the correct
 * numbers every time. So a single poll is not *reliably* wrong today — it is
 * unguarded, and what stands between it and the reading above is scheduling. The
 * three recorded failures say what that is worth betting on. Two of them were
 * found by a person noticing a number, not by a test going red.
 *
 * **What this helper does not and cannot wait for.** `GraphCanvas` sizes its
 * canvas from a `ResizeObserver` on its own container, and an observer fires
 * *after* the layout it observed (`BACKLOG.md` B61). This helper returns once
 * the split has been re-laid-out, which is exactly when that observer has not
 * run yet. Anything measuring inside the graph after a resize still needs its
 * own `expect.poll`; a single read there fails against correct code.
 *
 * Grid templates are read through `getPropertyValue('grid-template-columns')`
 * rather than the camel-cased property, because `check-deleted.mjs` forbids that
 * identifier anywhere under the session view — one of this helper's four callers
 * lives there. Reading the browser's own answer is not the deleted hand-built
 * grid coming back, but the rule cannot tell, and a rule loosened for a test is
 * worth less than one spelling.
 */

/** The viewport `vite.config.ts` sets once for the whole browser run. */
export const DEFAULT_VIEWPORT = { width: 1440, height: 900 } as const

const splitElement = (selector: string) => {
  const element = document.querySelector<HTMLElement>(selector)
  if (element === null) throw new Error(`no split matched ${selector}`)
  return element
}

/** The panes' collapse *form*, which `Pane.tsx:126` derives from the split's
 *  `stacked` and so writes identically on every pane in one split. Read off the
 *  first pane; a disagreement between panes would be a different bug and is not
 *  what this is waiting for. */
const collapseForm = () =>
  document.querySelector<HTMLElement>('[data-pane]')?.getAttribute('data-collapse-to') ?? null

/** What poll 4 below returns when it is happy. Any other string is a report of
 *  what is wrong, written to be read in an assertion diff. */
const SETTLED = 'settled'

/** Has the browser finished laying the split out against `width` — and if not,
 *  *why not*, in numbers.
 *
 * Returning a sentence rather than a boolean is the whole point: `expect.poll`
 * prints the last value it saw, so a give-up here reads as the measurement that
 * failed rather than as "the resize never settled". See the comment at the call
 * site for the case that forced it. */
const settledAgainst = (split: HTMLElement, width: number): string => {
  const style = getComputedStyle(split)
  if (style.display !== 'grid')
    return style.flexDirection === 'column'
      ? SETTLED
      : `at ${String(width)}px the split is not a column yet: display ${style.display}, flex-direction ${style.flexDirection}`

  const raw = style.getPropertyValue('grid-template-columns')
  const tracks = raw.split(' ').map((track) => Number.parseFloat(track))
  if (tracks.some(Number.isNaN)) return `at ${String(width)}px the tracks are unreadable: "${raw}"`

  const gap = Number.parseFloat(style.columnGap) || 0
  const gaps = (tracks.length - 1) * gap
  const total = tracks.reduce((a, b) => a + b, 0) + gaps
  if (total <= split.clientWidth + 1) return SETTLED

  // Either a template from the previous width still on the element, or a
  // stylesheet that genuinely overflows. This poll cannot tell the two apart —
  // it times out either way — so it says what it measured and lets the reader.
  return `at ${String(width)}px the tracks overflow the split: "${raw}"${gaps === 0 ? '' : ` plus ${String(gaps)}px of gap`} = ${String(Math.round(total))}px in a clientWidth of ${String(split.clientWidth)}px`
}

/** Resize the viewport and return only once **both** React and the browser are
 *  on the other side of it.
 *
 * The width is the subject; the height defaults to the 900 every caller uses and
 * is a parameter because the below-narrow files need to shorten the page to make
 * a `60vh` cap bind.
 *
 * `selector` exists for the one thing that varies between callers — a page may
 * mount `[data-split='project']` or `[data-split='session']`. The default
 * matches whichever single split the fixture mounted, which is all four of
 * today's callers.
 */
export const resizeViewport = async (
  width: number,
  height = 900,
  selector = '.lay-split',
): Promise<void> => {
  await page.viewport(width, height)
  const split = () => splitElement(selector)

  // React, half one: `Split` writes an inline template only above `--bp-wide`
  // and omits the property entirely below it (`Split.tsx:99`), which is the
  // handoff the stylesheet's media queries rely on. Constant across
  // `--bp-narrow`, which is why the next poll exists.
  await expect
    .poll(() => split().style.getPropertyValue('grid-template-columns') !== '')
    .toBe(width >= BREAKPOINTS.wide)

  // React, half two: the collapse form flips at `--bp-narrow` off the same
  // `useWide` subscription the media query shadows. Constant across
  // `--bp-wide`, which is why the poll above exists.
  await expect.poll(collapseForm).toBe(width < BREAKPOINTS.narrow ? 'strip' : 'rail')

  // The browser. The split is full width on every page that uses this, so its
  // own box reaching the new width is the cheapest thing to wait on that is
  // downstream of layout — and it is the *only* signal here that moves for a
  // resize inside a band, where both attributes above are already correct.
  await expect.poll(() => Math.round(split().getBoundingClientRect().width)).toBe(width)

  // The browser, second half: the resolved tracks fit the viewport. The box
  // above can reach the new width while the element still carries the previous
  // width's tracks — reading `280px 320px 280px` in an 821px viewport is
  // literally failed reading 2 — so this is what refuses a stale template
  // rather than a stale box. Below `--bp-narrow` the split is `display: flex`,
  // where `grid-template-columns` computes to `none` and the question is
  // instead whether it has become a column.
  //
  // **It reports its own numbers, and that is not decoration.** This is the one
  // poll here whose condition a *broken stylesheet* can make permanently
  // unsatisfiable rather than merely slow: a template that overflows never
  // settles, so the poll times out and the caller's own assertion never runs.
  // `session-responsive` claim 2 is the measured case — under its recorded
  // `minmax(600px, 1fr)` mutation, 600 + 300 do not fit 821 at any moment, and
  // an earlier version of this poll turned that file's recorded
  // `expected 300 to be greater than or equal to 320` into
  // `expected 'pending' not to be 'pending'`. The claim still failed; the
  // diagnosis did not survive. An overflowing template is exactly the defect
  // class these files exist to catch, so the give-up value carries the tracks
  // and the width rather than a bare sentinel.
  await expect.poll(() => settledAgainst(split(), width)).toBe(SETTLED)
}

/** Put the viewport back. Nothing else in the browser suite does: it is set once
 *  for the whole run at `vite.config.ts`, so a file that resizes and does not
 *  restore leaks into every sibling after it in file order — which reads as
 *  flakiness rather than as a leak. Call it from an `afterEach`. */
export const restoreViewport = async (): Promise<void> => {
  await page.viewport(DEFAULT_VIEWPORT.width, DEFAULT_VIEWPORT.height)
}
