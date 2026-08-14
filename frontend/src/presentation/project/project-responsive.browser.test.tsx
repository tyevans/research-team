import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { afterEach, expect, it, vi } from 'vitest'

import { createSessionStore } from '@application/session/session-store.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Container } from '@app/container.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'
import { OverlayHost } from '@presentation/layout/OverlayHost.tsx'
import { StreamProvider } from '@presentation/shell/StreamProvider.tsx'

import { ProjectView } from './ProjectView.tsx'

/** What the project page does between 821px and 1180px, which until this file
 *  nobody had looked at.
 *
 * `ProjectView.browser.test.tsx` is scoped in its docstring to "above
 * `--bp-wide`, the only band in which a `Split` writes a template at all", and
 * that sentence stays true — this is the other band, in a separate file, and
 * the two do not overlap. The fake container is that file's, copied rather than
 * shared: extracting it would couple two files whose fixtures will diverge as
 * soon as task B gives these regions real content, and nine ports of `vi.fn` is
 * a cheaper duplication than a shared harness nobody may change.
 *
 * **This is the first file in the repository to resize the viewport.** The
 * other nineteen treat `vite.config.ts`'s 1440x900 as fixed and say so in
 * prose. `page.viewport(w, h)` from `@vitest/browser` was spiked first, because
 * the whole shape of this file depends on it: proved on 2026-08-14 that it
 * re-triggers `matchMedia`, that `useWide`'s `useSyncExternalStore`
 * subscription (`use-wide.ts:33-51`) observes the change, and that React
 * re-renders — a probe reading both breakpoints went `true/true` at 1440,
 * `false/true` at 1000, `false/false` at 700 and back. No second vitest project
 * was needed.
 *
 * The two costs of that, both handled below rather than discovered: the
 * viewport is global to the run and nothing else restores it (see `afterEach`),
 * and awaiting the resize is not awaiting the re-render (see `widen`).
 */

const ATLAS = ProjectId('11111111-1111-1111-1111-111111111111')
const HOLDER = SessionId('3f2a0000-0000-0000-0000-000000000000')

const COURSE = {
  projectId: ATLAS,
  projectName: 'atlas',
  holdingSessionId: HOLDER,
  preset: { id: 'hybrid.default', name: 'Hybrid', version: '1' },
  position: 1,
  stageCount: 1,
  stages: [
    {
      index: 1,
      id: 'step0.intake',
      name: 'Intake',
      kind: 'author',
      spine: 0,
      scopeLevel: 'course',
      status: 'current',
      outputs: [],
      gateDecisions: [],
      reviewerRole: null,
      findingsReport: null,
    },
  ],
  findings: [],
  unimplementedChecks: [],
}

const container = () =>
  ({
    preferences: new InMemoryPreferenceStore(),
    now: () => new Date('2026-08-10T00:00:00Z'),
    stream: { connect: vi.fn(), disconnect: vi.fn() },
    projects: { course: vi.fn().mockResolvedValue(COURSE) },
    sessions: {
      read: vi.fn().mockResolvedValue({
        id: HOLDER,
        projectId: ATLAS,
        startedAt: '2026-08-10T00:00:00Z',
        forkedFrom: null,
        forkedAt: null,
        files: [],
        messages: [],
        compactedThrough: null,
      }),
      log: vi.fn().mockResolvedValue([]),
    },
    turns: {
      current: vi.fn().mockResolvedValue({
        running: false,
        turnIndex: null,
        startedAt: null,
        elapsedSeconds: null,
      }),
      activity: vi.fn().mockResolvedValue(null),
    },
    workers: {
      on: vi.fn().mockResolvedValue({ projectId: ATLAS, workers: [], idleSessionIds: [] }),
    },
    extractions: { on: vi.fn().mockResolvedValue({ current: [], last: [] }) },
    research: { current: vi.fn().mockResolvedValue(null) },
    topics: { queue: vi.fn().mockResolvedValue([]) },
    autonomy: { read: vi.fn().mockResolvedValue(null) },
  }) as unknown as Container

const show = async () => {
  const deps = container()
  const store = createSessionStore({
    sessions: deps.sessions,
    turns: deps.turns,
    now: deps.now,
    notify: () => {},
  })
  await render(
    <ContainerProvider container={deps}>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <StreamProvider>
          <OverlayHost>
            <div style={{ height: '900px', display: 'flex', flexDirection: 'column' }}>
              <ProjectView projectId={ATLAS} selection={null} store={store} />
            </div>
          </OverlayHost>
        </StreamProvider>
      </QueryClientProvider>
    </ContainerProvider>,
  )
  await expect.element(page.getByRole('region', { name: 'Event log' })).toBeVisible()
  return { preferences: deps.preferences as InMemoryPreferenceStore }
}

const split = () => document.querySelector<HTMLElement>('.lay-split[data-split="project"]')!
const pane = (id: string) => document.querySelector<HTMLElement>(`[data-pane="${id}"]`)!
const box = (id: string) => pane(id).getBoundingClientRect()

/** Column count as the browser resolved it, which is the whole subject here:
 *  a `grid-template-columns` of one track is the defect, two is the fix, and
 *  three is `Split`'s inline template above the breakpoint. */
const columns = () => getComputedStyle(split()).gridTemplateColumns.split(' ')

/** Resize and wait for React to have re-rendered on the other side of it.
 *
 * `page.viewport` resolves when the iframe has been resized, which is not when
 * `matchMedia` has fired, `useWide`'s `useSyncExternalStore` subscription has
 * observed it and React has committed.
 *
 * **Polling `window.innerWidth` is not enough, and this helper did that first.**
 * It is downstream of the resize and upstream of the render: claim 1 read three
 * columns at 1000px on the first run, because `innerWidth` already said 1000
 * while `Split` still had `wide === true` and its inline three-track template
 * still on the element. The poll has to be on something React writes, so it is
 * the inline style: `splitTemplate` returns `undefined` below `--bp-wide` and
 * React omits the property entirely, which is the same handoff the stylesheet
 * relies on. */
const widen = async (width: number) => {
  await page.viewport(width, 900)
  await expect.poll(() => split().style.gridTemplateColumns === '').toBe(width < 1181)
}

// Nothing else resets it. The viewport is global to the whole browser run
// (`vite.config.ts:288` sets 1440x900 once) and no other file in the suite
// touches it, so a test here that resized and did not restore would leak into
// every sibling that happens to run after it -- in file order, which is the
// kind of failure that reads as flakiness.
afterEach(async () => {
  await page.viewport(1440, 900)
})

/** Claim 1. In the 821-1180 band the project split is two columns with MATERIAL
 *  wrapped beneath them -- not the single column it resolved to for the whole
 *  of increment C.
 *
 * **Proved red** with the `[data-split='project']` block commented out of
 * `responsive.css`, at 1000x900:
 *
 *     AssertionError: expected [ '1000px' ] to have a length of 2 but got 1
 *
 * and the row heights behind that failure were `375.98px 375.98px 148.03px` --
 * three regions stacked in one column, each still drawing itself as a column.
 */
it('gives the project split two columns and a wrapped MATERIAL between 821 and 1180', async () => {
  await show()
  await widen(1000)

  expect(columns()).toHaveLength(2)

  // QUEUE and HOLDER are side by side on the top row: same top edge, and
  // HOLDER starts where QUEUE ends rather than under it.
  const queue = box('queue')
  const holder = box('holder')
  expect(holder.top).toBe(queue.top)
  expect(holder.left).toBeGreaterThanOrEqual(queue.right - 1)

  // HOLDER carries the extra weight, which is the one thing the arrangement
  // decides that the column count does not.
  expect(holder.width).toBeGreaterThan(queue.width)

  // MATERIAL is below both and spans the pair.
  const material = box('material')
  expect(material.top).toBeGreaterThanOrEqual(holder.bottom - 1)
  expect(Math.round(material.width)).toBe(Math.round(queue.width + holder.width))
})

/** Claim 2. Every region clears its floor in the band, and the top row keeps
 *  the majority of the height whatever MATERIAL holds.
 *
 * The measurement this slice was opened by: at 1000x900 the three panes were
 * rows of `375.98px 375.98px 148.03px` in one column, so QUEUE and HOLDER had
 * 376px of a 900px viewport each and neither had its width. `display: grid` in
 * this band means `layout.css`'s stacked-mode `max-height: 60vh` does not
 * apply and the surface owns the viewport, so nothing scrolled either.
 *
 * **The obvious assertion here was wrong and the mistake is worth recording.**
 * This first asserted `material.height > 300` — "MATERIAL is no longer
 * squeezed" — and it stayed red *after* the fix, at 149.03px. The wrapped row
 * is `minmax(0, auto)`: 46vh is a cap, not a height, and this fixture's
 * MATERIAL has no documents and no graph, so it is 149px tall because that is
 * what it contains. A pane that is content-sized measures the fixture, not the
 * arrangement.
 *
 * What is fixture-independent is the other side of the cap: the top row cannot
 * be given less than 54vh no matter how tall MATERIAL's content grows. That is
 * the guarantee the arrangement actually makes.
 *
 * **Proved red** with the `[data-split='project']` block commented out of
 * `responsive.css`, at 1000x900:
 *
 *     AssertionError: expected 375.984375 to be greater than or equal to 486
 */
it('keeps every region above its floor in the band', async () => {
  await show()
  await widen(1000)

  expect(box('queue').width).toBeGreaterThanOrEqual(280)
  expect(box('holder').width).toBeGreaterThanOrEqual(320)

  // The top row's floor, which is 900 minus MATERIAL's 46vh cap. Asserted on
  // both panes because they are the two that hold a reader's attention and a
  // template that gave the row to one of them would pass on the other.
  const topRow = 900 - 0.46 * 900
  expect(box('queue').height).toBeGreaterThanOrEqual(topRow)
  expect(box('holder').height).toBeGreaterThanOrEqual(topRow)

  // And the cap is on. Vacuous against this fixture — MATERIAL is 149px here
  // because it is empty, well under 414 — so this fires only once the region
  // has its real content, which is the slice after this one. Left in rather
  // than deleted: it is the assertion that catches the cap being dropped, and
  // it costs nothing.
  expect(box('material').height).toBeLessThanOrEqual(0.46 * 900 + 1)
})

/** Claim 3. Folding a flank in the band gives it the 34px rail it asks for.
 *
 * `Pane.tsx:126` keys the rail form on `stacked` rather than `!wide`, so in
 * this band a collapsed pane rotates its title and asks for a rail -- and until
 * now no template granted one. This is the half of the defect that a reader
 * would have met by clicking rather than by resizing.
 *
 * **Proved red** with the block commented out:
 *
 *     AssertionError: expected 1000 to be close to 34, received difference 966
 *
 * — the folded QUEUE was a full-width 1000x182px block with a vertical title.
 */
it('gives a folded flank its rail width in the band', async () => {
  await show()
  await widen(1000)

  await page.getByRole('button', { name: 'Collapse Queue' }).click()
  await expect.poll(() => box('queue').width).toBeCloseTo(34, 0)

  // The rail is a rail and not a strip: still a column beside HOLDER, still on
  // the top row. This is what `stacked` being false in the band buys.
  expect(box('holder').top).toBe(box('queue').top)
  expect(getComputedStyle(pane('queue')).getPropertyValue('--rail-w').trim()).toBe('34px')

  // And the space it gave up went to HOLDER rather than nowhere.
  expect(box('holder').width).toBeGreaterThan(900)
})

/** Claim 5. Folding *both* flanks rails both of them.
 *
 * Two clicks reach this and claim 3 does not cover it. `toggleCollapsed`
 * (`split-tracks.ts:98`) refuses only when every pane would close, so with three
 * tracks QUEUE and HOLDER can both be folded while MATERIAL stays open — and the
 * two single-collapse rules have identical specificity and each write the whole
 * `grid-template-columns`, so when both match the later one wins outright and
 * the other pane keeps a full track under a rotated title.
 *
 * The rails are asserted rather than the template string, because the template
 * is what was wrong: reading `grid-template-columns` back would have agreed with
 * whichever rule won.
 *
 * **Proved red** with only the combined `:has():has()` rule removed and the two
 * single rules left in place, at 1000x900:
 *
 *     AssertionError: expected 966 to be close to 34, received difference is 932
 *
 * — QUEUE at 966px, because the HOLDER rule is written second and simply won.
 */
it('rails both flanks when both are folded', async () => {
  await show()
  await widen(1000)

  await page.getByRole('button', { name: 'Collapse Queue' }).click()
  await expect.poll(() => box('queue').width).toBeCloseTo(34, 0)
  await page.getByRole('button', { name: 'Collapse Holding session' }).click()
  await expect.poll(() => box('holder').width).toBeCloseTo(34, 0)

  // Both, after the second fold. The first is re-read here rather than trusted
  // from the poll above: the whole defect is the second collapse silently
  // undoing the first pane's track.
  expect(box('queue').width).toBeCloseTo(34, 0)
  expect(box('holder').width).toBeCloseTo(34, 0)

  // Still the top row, and MATERIAL still spans it — folding two flanks is not
  // a way to reach a different arrangement.
  expect(box('holder').top).toBe(box('queue').top)
  expect(box('material').top).toBeGreaterThanOrEqual(box('queue').bottom - 1)
})

/** Claim 6. At the band's own bottom edge, QUEUE still clears its measured
 *  floor.
 *
 * 821 is the narrowest viewport at which this arrangement applies at all — one
 * pixel lower and `layout.css` takes over with a flex column — so it is the
 * width at which the two columns are thinnest and the only one where a floor
 * can bind. Nothing tested it: claim 4 asserts 1181 and 1180, both at the top.
 *
 * The floor is `PROJECT_TRACKS`'s **measured** 344 for QUEUE, below which the
 * seeding form (317px, and it does not wrap) paints outside a box that clips it
 * with no scroller and no ellipsis. Asserted against the same number the tracks
 * declare rather than against the fr share, because the share is what the
 * template produces and the floor is what it owes.
 *
 * **HOLDER is asserted too and it is the passing half.** Its floor is 342 and
 * its share here is ~479, so it never binds anywhere in this band; that is a
 * fact worth pinning rather than leaving implicit, since the obvious "raise both
 * to match the tracks" edit would be justified by nothing.
 *
 * **Proved red** at 821x900 against the `minmax(280px, 1fr)` this block shipped
 * in round 1:
 *
 *     AssertionError: expected 342.078125 to be greater than or equal to 344
 *
 * — which settles the arithmetic that predicted it: 821 x (1 / 2.4) = 342.08,
 * two pixels under a floor that was measured, not chosen. The range is ~5px
 * wide and nobody would have looked, because the comment above the template
 * said the minima never bind.
 */
it('clears QUEUE’s measured floor at the bottom of the band', async () => {
  await show()
  await widen(821)

  expect(columns()).toHaveLength(2)
  expect(box('queue').width).toBeGreaterThanOrEqual(344)
  expect(box('holder').width).toBeGreaterThanOrEqual(342)

  // The two still fill the row: raising a floor moves the boundary between them
  // rather than adding a gap or overflowing the viewport.
  expect(Math.round(box('queue').width + box('holder').width)).toBe(821)
})

/** Claim 4. The new rule stops at `--bp-wide`, where `Split`'s inline template
 *  takes over again.
 *
 * The boundary is asserted because the rule is written with range syntax
 * against the same literals `layout-tokens.ts` hands to `matchMedia`, and an
 * off-by-one there would put a two-column media query and a three-column inline
 * style on the same element at 1181 — where the inline style silently wins and
 * the `grid-template-rows` from the media query does not. That combination
 * lays out, so nothing would look obviously wrong.
 *
 * **Proved red**, which was not the prediction — this was written expecting to
 * pass against the unfixed CSS, on the reasoning that a boundary guard's
 * subject is the edit that would break it rather than the state before it. It
 * fails at its lower half, because 1180 is inside the band and the band had no
 * rule:
 *
 *     AssertionError: expected [ '1180px' ] to have a length of 2 but got 1
 *
 * The 1181 half is the one that would have passed either way, and it is the
 * half that guards the boundary. Both are kept.
 */
it('hands the layout back to Split at 1181', async () => {
  await show()
  await widen(1181)
  expect(columns()).toHaveLength(3)

  await widen(1180)
  expect(columns()).toHaveLength(2)
})
