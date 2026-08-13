import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { expect, it, vi } from 'vitest'

import { createSessionStore } from '@application/session/session-store.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Container } from '@app/container.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'
import { OverlayHost } from '@presentation/layout/OverlayHost.tsx'
import { StreamProvider } from '@presentation/shell/StreamProvider.tsx'

import { ProjectView } from './ProjectView.tsx'

/** That a `Split` inside a `Split` actually lays out, which is the one claim
 *  slice 0 made and could not check.
 *
 * The slice's report argued the nesting from mechanism — nearest-provider
 * context, two group strings, two inline templates on two elements — and every
 * one of those is invisible to the jsdom suite. `vitest.setup.ts` pins
 * `offsetWidth`/`offsetHeight` to constants and answers `false` to every media
 * query, so there the project split writes no template at all and every element
 * is 800x600 whatever the grid does. Three green jsdom tests about this file
 * said nothing about any of it.
 *
 * **This mounts the real `ProjectView`, not a harness of `Split` and `Pane`.**
 * `SessionView.test.tsx` records why, and its reasoning transfers exactly: the
 * defect this guards against is one prop on one pane — HOLDER's
 * `scroll="regions"` — and a harness that composed the primitives correctly
 * would assert the harness. The cost is a fake container of nine ports, which
 * is the largest setup in this directory and is the reason the gap existed.
 *
 * The viewport is 1440x900 and is set in `vite.config.ts`, not by anything
 * here: every assertion below is above `--bp-wide`, which is the only band in
 * which a `Split` writes a template at all.
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

/** Only the ports this page and its store reach for. A fake that implemented
 *  the whole container would hide which dependencies the page really has, and
 *  the list below is itself informative: the project page touches nine. */
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
          {/* A real height, because every claim here is about how height
              travels down the nesting and a page that sizes to its content
              would make all of them vacuous. */}
          <OverlayHost>
            <div style={{ height: '900px', display: 'flex', flexDirection: 'column' }}>
              <ProjectView projectId={ATLAS} selection={null} store={store} />
            </div>
          </OverlayHost>
        </StreamProvider>
      </QueryClientProvider>
    </ContainerProvider>,
  )

  // The nested split only exists once the course resolves and names a holding
  // session, so every test waits on something the inner tree renders.
  await expect.element(page.getByRole('region', { name: 'Event log' })).toBeVisible()

  return { preferences: deps.preferences as InMemoryPreferenceStore }
}

const splits = () => ({
  outer: document.querySelector<HTMLElement>('.lay-split[data-split="project"]')!,
  inner: document.querySelector<HTMLElement>('.lay-split[data-split="session"]')!,
})

/** Claim 1. The transcript gets a box with a height in it.
 *
 * **Proved red**: changing HOLDER's `Pane` from `scroll="regions"` to the
 * default in `ProjectView.tsx` fails this at `expected 340.84375 to be greater
 * than 898` — the inner split stops at its content's height 557px short of the
 * body's bottom, because `layout.css:221` makes the default body an
 * `overflow: auto` block, a block box is not a flex container, and the split's
 * `flex: 1 1 auto` then means nothing. Note what that failure is *not*: the
 * split still has a height, the transcript still renders, and nothing errors.
 * It is a page that scrolls in the wrong box, which is the shape of defect this
 * suite exists for.
 */
it('gives the nested split the height of the pane holding it', async () => {
  await show()
  const { inner } = splits()
  const body = inner.closest('.lay-pane-body')!

  const nested = inner.getBoundingClientRect()
  const holder = body.getBoundingClientRect()

  expect(nested.height).toBeGreaterThan(0)
  // **Not** "the split is as tall as the body", which is what this asserted
  // first and which failed at 815 against 861.5. `SessionView` renders its own
  // header and scrub bar above its `Split`, so the split gets what is left --
  // and it should, since the alternative is a page taller than its pane. The
  // claim that survives that correction is the one actually worth making: the
  // split takes *all* the leftover height, so its bottom edge lands on the
  // body's. Reasoned from the first failure rather than tuned to pass it -- a
  // threshold like `> holder * 0.9` would have gone green here while a split
  // that stopped halfway down also would.
  expect(nested.bottom).toBeGreaterThan(holder.bottom - 2)
  // And it does not overflow the pane it is in, which is the other failure —
  // an inner scroller taller than its container gives a box scrolling inside a
  // box, where the outer one absorbs the wheel.
  expect(nested.bottom).toBeLessThanOrEqual(holder.bottom + 1)
  // The body itself must not be a scroller. `regions` is what makes that true,
  // and it is the prop this whole test guards.
  expect(body.scrollHeight).toBeLessThanOrEqual(body.clientHeight + 1)
})

/** Claim 2. Two templates, on two elements, neither overwriting the other.
 *
 * This is the mechanism the slice report argued from, asserted as the mechanism
 * rather than as a symptom. `splitTemplate` writes `grid-template-columns`
 * inline; an inline style outranks any stylesheet unconditionally, so "one
 * split silently restyles the other" is the failure worth ruling out, and the
 * ruling-out is that they are different elements with different values.
 *
 * **Proved red**, and the inversion is worth reading rather than trusting.
 * Giving `PROJECT_TRACKS` the same three numbers as `SESSION_TRACKS`
 * (`280/1.05`, `320/1.5`, `280/1.05`) fails the inequality — two identical
 * strings. That is a weaker inversion than the other two and I will not pretend
 * otherwise: identical tracks are not the same event as one split overwriting
 * the other's style. What it does establish is that the assertion
 * discriminates, which is the thing a green test has to earn. The `not.toBe('')`
 * halves carry the rest: an empty template means the wide branch never ran and
 * the whole test measured nothing.
 */
it('writes one grid template per split, on the split it belongs to', async () => {
  await show()
  const { outer, inner } = splits()

  const outerTemplate = outer.style.gridTemplateColumns
  const innerTemplate = inner.style.gridTemplateColumns

  expect(outerTemplate).not.toBe('')
  expect(innerTemplate).not.toBe('')
  expect(outerTemplate).not.toBe(innerTemplate)
  // The values are `PROJECT_TRACKS` and `SESSION_TRACKS` respectively, and the
  // floors are what tell them apart: the project page's queue column is 280px
  // against the session workspace's 320px. Asserted as "contains the minimum"
  // rather than as the whole string, because the whole string is three
  // `minmax()` calls a browser may serialise its own way.
  expect(outerTemplate).toContain('320px')
  expect(innerTemplate).toContain('320px')
  expect(outer.querySelectorAll(':scope > .lay-pane')).toHaveLength(3)
  expect(inner.querySelectorAll(':scope > .lay-pane')).toHaveLength(3)
})

/** Claim 3. Folding a region does not fold a session pane, or the reverse.
 *
 * **Proved red**: pointing `use-project-panes.ts`'s `GROUP` at `'session'` fails
 * the last pair at `expected [] to deeply equal [ 'queue' ]`. The failure is
 * one step off what I predicted, and the step is the informative part: nothing
 * is written under `project` at all, and both splits' folds land in one key,
 * where the later write replaces the earlier rather than joining it. So a
 * reader who folded QUEUE and then the event log would come back to a page with
 * one of the two remembered and no way to tell which. Note also what did *not*
 * go red — the on-screen assertions above all still passed with one group,
 * because the context is genuinely per-`Split` and the folds only collide in
 * storage. The crosstalk this page could actually have shipped is a stored one.
 */
it('folds a region without folding a session pane, and remembers them apart', async () => {
  const { preferences } = await show()
  const { outer, inner } = splits()

  await page.getByRole('button', { name: 'Collapse Queue' }).click()

  expect(outer.querySelector('[data-pane="queue"]')!.className).toContain('is-collapsed')
  // Every session pane still open. `Event log` is the one a shared context or a
  // shared track list would have taken with it, since it is the inner split's
  // first pane just as `queue` is the outer's.
  for (const pane of ['timeline', 'workspace', 'conversation']) {
    expect(inner.querySelector(`[data-pane="${pane}"]`)!.className).not.toContain('is-collapsed')
  }

  await page.getByRole('button', { name: 'Collapse Event log' }).click()

  expect(inner.querySelector('[data-pane="timeline"]')!.className).toContain('is-collapsed')
  expect(outer.querySelector('[data-pane="holder"]')!.className).not.toContain('is-collapsed')
  expect(outer.querySelector('[data-pane="material"]')!.className).not.toContain('is-collapsed')

  // Two keys, each holding only its own split's pane. This is the assertion the
  // one-group inversion above breaks.
  expect(preferences.collapsedPanes('project')).toEqual(['queue'])
  expect(preferences.collapsedPanes('session')).toEqual(['timeline'])
})

/** Claim 4. The queue header keeps its height, and the queue scrolls past it.
 *
 * `QueueHeader`'s docstring makes exactly this claim -- "not a scroller", so
 * that the pane body below it stays the one scroller -- and it is the reason
 * slice 0's four loose panels needed re-parenting at all: parked directly in
 * the pane, the run panel scrolled away with the stage list under it. Which box
 * owns the overflow is not something jsdom holds an opinion about, so this is
 * asserted here or it is asserted nowhere.
 *
 * **The obvious assertion does not work, and the failure is worth recording.**
 * This first asserted `header.scrollHeight <= clientHeight` — "nothing is
 * clipped" — and adding `flex-1 overflow-auto` to the header did not fail it.
 * The fixture's one stage and four small panels do not fill 900px, so a header
 * that *is* a scroller has nothing to scroll and measures identically to one
 * that is not. A test that only fires when the data happens to be tall is a
 * test that reports on the fixture.
 *
 * So the claim is asserted as the two declarations that make it true, read back
 * from the browser's own cascade. That is not a restatement of the class list:
 * `overflow-y` and `flex-grow` are computed from Tailwind utilities through
 * `@layer utilities`, and jsdom's `getComputedStyle` returns only what an
 * inline style said — it answers `''` for both, and would pass whatever the
 * header were dressed in.
 *
 * **Proved red**: `flex-1 overflow-auto` on the header fails at
 * `expected "auto" to be "visible"`.
 */
it('keeps the queue header out of the queue pane’s scroller', async () => {
  await show()
  const header = document.querySelector<HTMLElement>('[data-region-header="queue"]')!
  const body = header.closest('.lay-pane-body')!

  expect(header.getBoundingClientRect().height).toBeGreaterThan(0)
  // In QUEUE and not merely somewhere that happens to render: which pane owns
  // these controls is the whole of the re-parenting.
  expect(body.closest('[data-pane]')!.getAttribute('data-pane')).toBe('queue')

  const style = getComputedStyle(header)
  // Not a scroller: the pane body below keeps the overflow.
  expect(style.overflowY).toBe('visible')
  // And it does not take the leftover height, which is the other half of the
  // same claim — a header that grows leaves the queue nothing to scroll in.
  expect(style.flexGrow).toBe('0')
})
