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

import { resizeViewport, restoreViewport } from '../../test/browser-viewport.ts'
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
 * viewport is global to the run and nothing else restores it, and awaiting the
 * resize is not awaiting the re-render. Both now live in
 * `src/test/browser-viewport.ts` rather than here — this file's own `widen()`
 * is one of the three failed readings that module's docstring records, and it
 * was deleted rather than kept beside it.
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
  // The tab strip rather than the Event log: the holding session is a tab now
  // and its region exists only while that tab is the open one. See
  // `project-tracks.browser.test.tsx`'s `show` for the same change and the
  // fifteen-second wait it was costing.
  await expect.element(page.getByRole('tablist', { name: 'Material' })).toBeVisible()
  return { preferences: deps.preferences as InMemoryPreferenceStore }
}

const split = () => document.querySelector<HTMLElement>('.lay-split[data-split="project"]')!
const pane = (id: string) => document.querySelector<HTMLElement>(`[data-pane="${id}"]`)!
const box = (id: string) => pane(id).getBoundingClientRect()

/** Column count as the browser resolved it, which is the whole subject here: a
 *  `grid-template-columns` of one track is the defect and two is the fix, in
 *  this band and in `Split`'s inline template above it alike. The two bands
 *  agreeing on the count is new -- the page had three columns above 1181 and
 *  two here until it became a sidebar over one content area -- so the
 *  hand-back at the breakpoint is now asserted through the *widths* rather
 *  than through the count, which no longer changes across it. */
const columns = () => getComputedStyle(split()).gridTemplateColumns.split(' ')

afterEach(restoreViewport)

/** Claim 1. In the 821-1180 band the project split is a sidebar beside a
 *  content area, not the single column it resolves to with no rule.
 *
 * **Proved red** with the `[data-split='project']` block commented out of
 * `responsive.css`, at 1000x900:
 *
 *     AssertionError: expected [ '1000px' ] to have a length of 2 but got 1
 *
 * and the row heights behind that failure were `450px 450px` — two regions
 * stacked in one column, each still drawing itself as a column.
 */
it('gives the project split a sidebar and a content column between 821 and 1180', async () => {
  await show()
  await resizeViewport(1000)

  expect(columns()).toHaveLength(2)

  // Side by side on one row: same top edge, MATERIAL starting where QUEUE ends
  // rather than under it. Both halves are needed — a stacked pair also has two
  // "columns" if only the count is read.
  const queue = box('queue')
  const material = box('material')
  expect(material.top).toBe(queue.top)
  expect(material.left).toBeGreaterThanOrEqual(queue.right - 1)

  // Nothing wraps and nothing is capped, which is what changed when the third
  // pane left: MATERIAL used to take its own row beneath the other two under a
  // 46vh cap, and now shares the full height of the split.
  expect(Math.round(material.height)).toBe(Math.round(queue.height))
  expect(material.width).toBeGreaterThan(queue.width)
})

/** Claim 2. QUEUE clears its measured floor across the band, and MATERIAL takes
 *  everything else.
 *
 * The floor is `PROJECT_TRACKS`'s measured 344, below which the seeding form
 * (317px, and it does not wrap) paints outside a box that clips it with no
 * scroller and no ellipsis. It binds across this whole band rather than at one
 * edge of it — 25% of 1180 is 295 — which is the difference between this rule
 * and the one it replaced, where the two flanks' shares crossed their floors
 * partway through and only the bottom ~5px was wrong.
 *
 * **Proved red** with the sidebar's `minmax(344px, 25%)` reduced to `25%`:
 *
 *     AssertionError: expected 250 to be greater than or equal to 344
 */
it('keeps the sidebar above its measured floor across the band', async () => {
  await show()

  for (const viewport of [1180, 1000, 821]) {
    await resizeViewport(viewport)
    expect(box('queue').width).toBeGreaterThanOrEqual(344)
    // The two fill the row: a floor that binds moves the boundary between them
    // rather than adding a gap or overflowing the viewport.
    expect(Math.round(box('queue').width + box('material').width)).toBe(viewport)
  }
})

/** Claim 3. Folding the sidebar in the band gives it the 34px rail it asks for.
 *
 * `Pane` keys the rail form on `stacked` rather than `!wide`, so in this band a
 * collapsed pane rotates its title and asks for a rail — and without a rule
 * here no template grants one. This is the half of the defect a reader meets by
 * clicking rather than by resizing.
 *
 * **Proved red** with the collapsed rule commented out:
 *
 *     AssertionError: expected 1000 to be close to 34, received difference 966
 *
 * — the folded QUEUE was a full-width 1000x182px block with a vertical title.
 */
it('gives the folded sidebar its rail width in the band', async () => {
  await show()
  await resizeViewport(1000)

  await page.getByRole('button', { name: 'Collapse Queue' }).click()
  await expect.poll(() => box('queue').width).toBeCloseTo(34, 0)

  // A rail and not a strip: still a column beside MATERIAL, still on the same
  // row. This is what `stacked` being false in the band buys.
  expect(box('material').top).toBe(box('queue').top)
  expect(getComputedStyle(pane('queue')).getPropertyValue('--rail-w').trim()).toBe('34px')

  // And the space it gave up went to MATERIAL rather than nowhere.
  expect(box('material').width).toBeGreaterThan(900)
})

/** Claim 4. The reader can get the sidebar back.
 *
 * The assertion that would have caught this slice's own rejected design. Folding
 * the sidebar automatically below the wide breakpoint was written and backed
 * out — `use-project-panes.ts` carries the reasoning — and its defect was
 * precisely that the expand control stayed present, named and focusable while
 * doing nothing, because the override re-folded the pane on the next render.
 * Every other assertion in this file passed under it.
 *
 * **Proved red** against that design: `expected 34 to be greater than 300`.
 */
it('lets the reader unfold the sidebar again in the band', async () => {
  await show()
  await resizeViewport(1000)

  await page.getByRole('button', { name: 'Collapse Queue' }).click()
  await expect.poll(() => box('queue').width).toBeCloseTo(34, 0)

  await page.getByRole('button', { name: 'Expand Queue' }).click()
  await expect.poll(() => box('queue').width).toBeGreaterThan(300)
})

/** Claim 5. The content area offers no fold at all.
 *
 * Where the three-pane page needed a rule for "both flanks folded at once" —
 * two clicks reached a state neither single rule covered — a sidebar layout
 * removes the state rather than styling it: MATERIAL declares
 * `collapsible={false}`, so there is one toggle on the page and no combination
 * to get wrong.
 *
 * Worth an assertion rather than left to `Pane.test.tsx` because the two say
 * different things. That test says the prop suppresses the button; this says
 * *the project page passes it*, at the width where a second fold would have
 * left the reader with two rails and nothing between them.
 */
it('offers no fold for the content area', async () => {
  await show()
  await resizeViewport(1000)

  expect(page.getByRole('button', { name: /Material/ }).elements()).toHaveLength(0)
  expect(page.getByRole('button', { name: 'Collapse Queue' }).elements()).toHaveLength(1)
})

/** Claim 6. The rule stops at `--bp-wide`, where `Split`'s inline template takes
 *  over again.
 *
 * The boundary is asserted because the rule is written with range syntax against
 * the same literals `layout-tokens.ts` hands to `matchMedia`, and an off-by-one
 * there would put a media query and an inline style on the same element at 1181
 * — where the inline style silently wins. That combination lays out, so nothing
 * would look obviously wrong.
 *
 * **Asserted through the inline style rather than the column count, and that is
 * a change this slice forced.** Both bands are two columns now, so the count
 * that used to distinguish them (three above, two below) says the same thing on
 * either side of the boundary and could not fail. What still differs is *who
 * writes the template*: `Split` sets `style.gridTemplateColumns` only when
 * `wide`, and leaves the property absent otherwise so the media query keeps its
 * say. That is the handoff, so that is what is read.
 *
 * **Proved red** by removing the `wide` guard from `splitTemplate`, which makes
 * the inline style present at 1180 too: `expected '' to be ''` fails at the
 * second assertion with `minmax(344px, 25%) minmax(537px, 1fr)`.
 */
it('hands the layout back to Split at 1181', async () => {
  await show()

  await resizeViewport(1181)
  expect(split().style.gridTemplateColumns).not.toBe('')
  expect(columns()).toHaveLength(2)

  await resizeViewport(1180)
  expect(split().style.gridTemplateColumns).toBe('')
  expect(columns()).toHaveLength(2)

  // And the two agree about the geometry across the boundary, which is the
  // point of writing the same declaration in both places: one pixel of viewport
  // must not move the sidebar.
  const below = box('queue').width
  await resizeViewport(1181)
  expect(box('queue').width).toBeCloseTo(below, 0)
})
