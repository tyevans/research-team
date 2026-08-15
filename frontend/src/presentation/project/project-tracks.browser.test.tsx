import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { afterEach, expect, it, vi } from 'vitest'

import { createSessionStore } from '@application/session/session-store.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Container } from '@app/container.ts'
import { ProjectId, SessionId, SourceId, TopicId } from '@domain/shared/identifier.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'
import { OverlayHost } from '@presentation/layout/OverlayHost.tsx'
import type { Selection } from '@presentation/routing/routes.ts'
import { StreamProvider } from '@presentation/shell/StreamProvider.tsx'

import { resizeViewport, restoreViewport } from '../../test/browser-viewport.ts'
import { ProjectView } from './ProjectView.tsx'
import { PROJECT_TRACKS } from './use-project-panes.ts'

/** Where each of the project page's three regions stops being usable — the
 *  measurement `PROJECT_TRACKS` deferred for four slices, taken on 2026-08-14.
 *
 * **The fixture is the point of this file, not its setup.** The docstring being
 * settled here deferred to "the slice that gives each region its real content",
 * because a floor measured against three empty regions is a floor for the
 * fixture. So QUEUE holds four stages and four topics, HOLDER holds a scrub bar
 * over an eight-message transcript, and MATERIAL holds six documents and a
 * twelve-node graph with the real `GraphCanvas` mounted. Every claim below is
 * measured with all three loaded, and claim 4 exists to fail if any of them
 * quietly empties.
 *
 * **The floor is defined mechanically**, because "usable" needs an assertion:
 * a region is below its floor when some element in it has `scrollWidth` past
 * its `clientWidth` and no scroller and no ellipsis to answer for it — content
 * painted outside a box that clips it and offers no way to reach it. Three
 * kinds of element are excluded from that and each exclusion is a decision:
 * scroll containers (they are supposed to overflow), anything with
 * `text-overflow: ellipsis` (truncation with a `TruncatedText` behind it is a
 * feature), and `.ent-topic-facts`, which `entity.css:208-222` clips *on
 * purpose* — that rule's own comment measured the loss and chose it over a row
 * that changes height. Counting it would have measured the topic fixture's chip
 * count rather than the page.
 *
 * The 1px slack matches `TruncatedText`'s: `scrollWidth` and `clientWidth` are
 * integers rounded from fractional layout, so a box sized exactly to its
 * content reports a 1px difference often enough to matter. It is also why the
 * three numbers are one or two pixels above what measured clean rather than
 * equal to it — 343px of QUEUE and 350px of MATERIAL clear the check only by
 * consuming that slack, which is not clearance.
 *
 * **The viewport is resized here**, which `project-responsive.browser.test.tsx`
 * established on the same day and whose two hazards this file inherits: wait on
 * something React or the browser has committed rather than on
 * `window.innerWidth`, and restore the viewport in an `afterEach` because
 * nothing else in the suite does.
 *
 * The container width and the viewport width are the same number on this page,
 * which is what makes resizing the viewport a fair way to drive the tracks:
 * `.lay-shell` and `.lay-surface` are both `flex-direction: column`
 * (`layout.css:32-62`), so nothing takes horizontal chrome off the split.
 */

const ATLAS = ProjectId('11111111-1111-1111-1111-111111111111')
const HOLDER = SessionId('3f2a0000-0000-0000-0000-000000000000')

/** The narrowest viewport at which `Split` writes a template at all, and so the
 *  only end of the wide band where a floor can bind. `layout-tokens.ts` hands
 *  the same literal to `matchMedia`. */
const BP_WIDE = 1181

const STAGES = [
  ['step0.intake', 'Intake', 'current'],
  ['step1.survey', 'Survey the literature', 'done'],
  ['step2.synthesis', 'Synthesis and contradiction hunt', 'done'],
  ['step3.review', 'Reviewer pass', 'pending'],
].map(([id, name, status], index) => ({
  index: index + 1,
  id,
  name,
  kind: 'author',
  spine: 0,
  scopeLevel: 'course',
  status,
  outputs: [],
  gateDecisions: [],
  reviewerRole: null,
  findingsReport: null,
}))

const COURSE = {
  projectId: ATLAS,
  projectName: 'atlas',
  holdingSessionId: HOLDER,
  preset: { id: 'hybrid.default', name: 'Hybrid', version: '1' },
  position: 1,
  stageCount: STAGES.length,
  stages: STAGES,
  findings: [],
  unimplementedChecks: [],
}

/** Questions of real length, because a topic row's question is the widest text
 *  QUEUE holds and a fixture of `'Topic 1'` would never reach an edge. */
const TOPICS = [
  'Which of the 2019 replication attempts actually reused the original instrument?',
  'Does the effect survive when the pre-registered exclusions are applied?',
  'Short one',
  'What did the funder require to be reported, and was it?',
].map((question, index) => ({
  topicId: TopicId(`aaaaaaaa-0000-0000-0000-00000000000${String(index)}`),
  question,
  status: index === 0 ? 'investigating' : 'open',
  sources: 3,
  findings: 1,
  openSubQuestions: 2,
  triggers: ['contested'],
  needsAttention: index === 0,
  isBlocked: index === 3,
}))

const DOCUMENTS = Array.from({ length: 6 }, (_, index) => ({
  sourceId: SourceId(`bbbbbbbb-0000-0000-0000-00000000000${String(index)}`),
  charCount: 40_000,
  sha256: 'f'.repeat(64),
  uri: `https://journals.example.org/vol12/issue3/article-${String(index)}`,
  title: `A very long document title that will not fit in a narrow column, number ${String(index)}`,
  publishedAt: '2024-03-01',
  note: null,
  droppedReason: null,
}))

const NODES = Array.from({ length: 12 }, (_, index) => ({
  id: `n${String(index)}`,
  name: `Consolidated Instrument Registry ${String(index)}`,
  entityType: index % 2 === 0 ? 'Organization' : 'Person',
}))

const GRAPH = {
  entities: NODES,
  relationships: NODES.slice(1).map((node) => ({
    source: 'n0',
    target: node.id,
    relationshipType: 'advised',
  })),
  truncated: false,
  inferredTruncated: false,
}

const MESSAGES = Array.from({ length: 8 }, (_, index) => ({
  role: index % 2 === 0 ? 'user' : 'assistant',
  content:
    'A message long enough to wrap in a narrow column and to give the transcript something to lay out.',
  toolCalls: [],
  isError: false,
}))

/** Twelve ports rather than `ProjectView.browser.test.tsx`'s nine: `topics`,
 *  `documents` and `graphs` are the three this file adds, and they are exactly
 *  the three that give QUEUE and MATERIAL something to be too narrow for. */
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
        messages: MESSAGES,
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
    topics: { list: vi.fn().mockResolvedValue(TOPICS) },
    documents: { list: vi.fn().mockResolvedValue(DOCUMENTS) },
    graphs: {
      whole: vi.fn().mockResolvedValue(GRAPH),
      search: vi.fn().mockResolvedValue({ entities: NODES, truncated: false }),
      neighborhood: vi.fn().mockResolvedValue({ root: NODES[0], entities: [], relationships: [] }),
    },
    autonomy: { read: vi.fn().mockResolvedValue(null) },
  }) as unknown as Container

const show = async (selection: Selection | null = null) => {
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
            {/* Full width and a real height, so the split's container is the
                viewport — which is what it is in the shell, and what makes
                resizing the viewport equivalent to resizing the split. */}
            <div style={{ height: '900px', display: 'flex', flexDirection: 'column' }}>
              <ProjectView projectId={ATLAS} selection={selection} store={store} />
            </div>
          </OverlayHost>
        </StreamProvider>
      </QueryClientProvider>
    </ContainerProvider>,
  )
  await expect.element(page.getByRole('region', { name: 'Event log' })).toBeVisible()
}

const pane = (id: string) => document.querySelector<HTMLElement>(`[data-pane="${id}"]`)!
const width = (id: string) => pane(id).getBoundingClientRect().width

// The local `resize` this file used to carry polled only the split's own box
// width. That is the *right* signal for this file — every resize here is 1440
// <-> 1181, inside the wide band, where no React-written attribute changes at
// all — and it is exactly the reason it could not be reused anywhere else. The
// shared helper keeps that poll and adds the two attribute polls the boundary
// crossings need; its docstring carries the three readings that were got wrong.
//
// `restoreViewport` for the reason the local `afterEach` gave: nothing else in
// the browser suite restores it, so a file that resizes and does not put it back
// leaks into every sibling after it in file order.
afterEach(restoreViewport)

/** Content painted outside a box that clips it, with no scroller and no
 *  ellipsis to reach it by. See this file's docstring for the three exclusions
 *  and why each one is not a defect. */
const clipped = (id: string): string[] => {
  const out: string[] = []
  for (const element of pane(id).querySelectorAll<HTMLElement>('*')) {
    if (element.clientWidth === 0) continue
    if (element.classList.contains('lay-visually-hidden')) continue
    if (element.classList.contains('ent-topic-facts')) continue
    const style = getComputedStyle(element)
    if (style.overflowX === 'auto' || style.overflowX === 'scroll') continue
    if (style.textOverflow === 'ellipsis') continue
    if (element.scrollWidth > element.clientWidth + 1)
      out.push(
        `${element.tagName.toLowerCase()}.${element.className} ${String(element.scrollWidth)} in ${String(element.clientWidth)}`,
      )
  }
  return out
}

/** Claim 1. At the narrowest viewport the wide band has, nothing in any region
 *  is painted outside a box that clips it.
 *
 * This is the measurement the docstring was waiting for, and it is taken at
 * 1181 rather than at 1440 because 1181 is where the tracks are tightest. The
 * page has been looked at only at 1440 for four slices, and 1440 was never the
 * width that was wrong.
 *
 * **Proved red** against the numbers this slice replaces (`280/320/280`), at
 * 1181x900, with this same fixture:
 *
 *     AssertionError: expected [ …(3) ] to deeply equal []
 *     + "div.lay-pane-body 351 in 337"
 *     + "div.flex min-h-0 flex-1 flex-col 351 in 337"
 *     + "div.tabs 351 in 337"
 *
 * and QUEUE fails on the same run once MATERIAL's assertion is taken out of the
 * way, at `+ "form.flex items-center gap-[8px] 317 in 310"` — its seeding form,
 * 14px later than MATERIAL's tab strip. HOLDER is the one region that stays
 * green under the inversion, which is what makes 342 the floor that never
 * binds.
 *
 * That is what the old numbers shipped: at 1181 MATERIAL got 337px for a tab
 * strip that is 351px wide and does not shrink, so **the Graph tab was painted
 * past the pane's right edge and could not be clicked** — the same shape as the
 * topic row's unreachable verbs that `entity.css:208` records. QUEUE's seeding
 * form went the same way 14px later.
 *
 * **The graph is why this assertion polls rather than reads once**, and the
 * reason is a real property of the page rather than test flakiness.
 * `GraphCanvas` sizes its canvas from a `ResizeObserver` on its own container
 * (see its comment on why the library's `window.innerWidth` default is
 * unusable here), and an observer fires after the layout it observed. Measured:
 * immediately after narrowing to 1181 the container's border box is already
 * 352 while the `<canvas>` inside it is still the 411 it was given at 1440 —
 * seven boxes reporting `411 in 352`, every one of them the canvas or an
 * ancestor of it. It settles within a few frames. A single read here would
 * fail against correct code, which is the failure `CLAUDE.md` warns costs a
 * morning if it is filed as flakiness.
 */
it('paints nothing outside its region at the narrowest wide viewport', async () => {
  await show({ facet: 'entity', id: null })
  // The graph tab, with the canvas actually drawn rather than its Suspense
  // fallback. `GraphCanvas` is `React.lazy` over `react-force-graph-2d`, so
  // without this wait MATERIAL is measured holding the string "loading the
  // graph canvas…" — which is exactly the "measured the fixture, not the page"
  // trap this file exists to avoid, and it was the state of this test until it
  // was checked. The canvas is `absolute inset-0` and contributes no intrinsic
  // width, so the three floors are the same either way; the graph's *chrome*
  // (legend, search, reset) is what is really being measured, and that renders
  // in both states.
  await expect.poll(() => pane('material').querySelectorAll('canvas').length).toBeGreaterThan(0)
  await resizeViewport(BP_WIDE)

  // MATERIAL first, because it is the region the old numbers actually broke
  // and an assertion order that reported QUEUE's smaller failure ahead of it
  // would bury the finding.
  await expect.poll(() => clipped('material'), { timeout: 5000, interval: 100 }).toEqual([])
  expect(clipped('queue')).toEqual([])
  expect(clipped('holder')).toEqual([])
})

/** Claim 2. The floors bind at 1181, and used to be inert at 1440 -- MATERIAL's
 *  no longer is.
 *
 * `minmax(min, 1fr)` takes the floor only when the fr share falls below it, so
 * raising three minima by 64, 22 and 72 pixels changed the page at the bottom
 * of the band and nowhere else, at the slice this file first measured: at 1440
 * the fr shares were 411/617/411, every one above its floor. Changing the
 * weights was the alternative and would have reshaped every width to fix one
 * end; that is why the floors were the lever.
 *
 * **Task 10's sixth tab moved MATERIAL's floor past its own fr share at 1440**,
 * which is the one place this claim's second half stopped holding. 422 is
 * above the 411 MATERIAL would get from `1fr`, so the floor binds there too
 * now -- MATERIAL is pinned across the whole wide band rather than only at
 * 1181, and QUEUE/HOLDER absorb the 11px the floor takes from them (411->407,
 * 617->611). QUEUE and HOLDER's floors are still inert at 1440; only
 * MATERIAL's claim changed.
 *
 * The numbers, re-measured in Chromium on 2026-08-14 after Task 10:
 *
 * | viewport | queue | holder | material |
 * | --- | --- | --- | --- |
 * | 1181 | 344 | 415 | 422 |
 * | 1440 | 407 | 611 | 422 |
 *
 * **Proved red** with the old minima restored: 1181 reads `337/506/337` and the
 * first assertion fails at `expected 337 to be 344`. Proved red again with
 * MATERIAL's floor still at 352 (this slice's starting point): 1440 reads
 * `411/617/411`, so `expected 411 to be 422` -- the case that used to pass
 * under the old-minima inversion and now has to be asserted on purpose instead
 * of assumed.
 */
it('binds the floors at 1181 and leaves 1440 alone', async () => {
  await show()

  await resizeViewport(BP_WIDE)
  expect(Math.round(width('queue'))).toBe(344)
  expect(Math.round(width('material'))).toBe(422)
  // HOLDER keeps what the two floors leave. Re-measured with MATERIAL's floor
  // -- 415 rather than 485, because MATERIAL's extra 70px (the sixth tab) comes
  // out of the same 1181 column and HOLDER is the one column with slack to
  // give up. Still far the widest column, and still well above its own floor
  // of 342 -- which is why HOLDER's number is the one that never binds in this
  // band.
  expect(Math.round(width('holder'))).toBe(415)

  await resizeViewport(1440)
  expect(Math.round(width('queue'))).toBe(407)
  expect(Math.round(width('holder'))).toBe(611)
  // **This is the one MATERIAL number Task 10 actually changed at 1440, and it
  // is a real behavioural shift, not a rounding artifact.** Before the sixth
  // tab, MATERIAL's fr share (411) already cleared its floor (352) and the
  // floor was inert here -- the class comment's whole claim 2. Now the floor
  // (422) is *above* the fr share MATERIAL would otherwise get, so it binds at
  // 1440 too: MATERIAL is pinned to its floor across the whole wide band
  // instead of only at 1181, and QUEUE/HOLDER absorb the difference (411->407,
  // 617->611). Measured, not reasoned -- proved red first at the old 411.
  expect(Math.round(width('material'))).toBe(422)
})

/** Claim 3. MATERIAL's floor is its tab strip, and the tab strip is a product
 *  constant rather than a fixture.
 *
 * The one region whose floor nothing about the data can move: five tabs whose
 * labels are declared in `ProjectView.tsx:119-125`, in a `.tabs` row with no
 * wrap and no scroller. Asserted as "the strip fits" rather than as "the strip
 * is 351px", because that number is a font measurement and would go red on a
 * label edit for the wrong reason. What must hold is that `PROJECT_TRACKS`'s
 * floor is at least what the strip needs.
 *
 * This is also the assertion that catches a sixth tab: a label arriving without
 * the floor moving fails here, at the width where it starts costing a reader a
 * tab.
 *
 * **Proved red** with `material`'s floor back at 280:
 *
 *     AssertionError: expected 337 to be greater than or equal to 351
 */
it('keeps MATERIAL wide enough for the tab strip it always has', async () => {
  await show()
  await resizeViewport(BP_WIDE)

  const tabs = pane('material').querySelector<HTMLElement>('.tabs')!
  expect(tabs.scrollWidth).toBeGreaterThan(300)
  expect(width('material')).toBeGreaterThanOrEqual(tabs.scrollWidth)

  const floor = PROJECT_TRACKS.find((track) => track.id === 'material')!.min
  expect(floor).toBeGreaterThanOrEqual(tabs.scrollWidth)
})

/** Claim 4. The fixture is loaded, which is what stops the three claims above
 *  from measuring an empty page.
 *
 * Not decoration. Task A's report records the trap immediately above this one:
 * an assertion about MATERIAL's height that was really an assertion about
 * MATERIAL being empty, green for the wrong reason. Every floor in this file
 * was measured with all three regions holding something, and a mock that
 * quietly stopped resolving would leave claims 1-3 green against three empty
 * columns.
 *
 * **Proved red** by pointing `documents.list` at `[]`:
 *
 *     AssertionError: expected '◂Collapse MaterialMaterialArtifactsWo…' to
 *     contain 'A very long document title'
 *     Received: "…ArtifactsWorkspaceFindingsDocumentsGraphNo documentsNothing
 *     has been stored in this corpus yet."
 *
 * **Claims 1-3 all stayed green under that inversion**, which is the argument
 * for this one existing: an emptied MATERIAL still has its tab strip, so the
 * floor assertions go on passing against a region with nothing in it.
 */
it('measures a page with all three regions loaded', async () => {
  await show({ facet: 'doc', id: null })
  await resizeViewport(BP_WIDE)

  // QUEUE: the topic queue, populated. The stage rail is beside it and is what
  // `ProjectView.browser.test.tsx` already covers.
  expect(pane('queue').querySelectorAll('.ent-topic-question').length).toBeGreaterThan(0)
  // HOLDER: a transcript with messages laid out in it.
  expect(
    pane('holder').querySelectorAll('[aria-label="Conversation"] .conv-scroll *').length,
  ).toBeGreaterThan(0)
  // MATERIAL: the documents the Documents tab is open on.
  expect(pane('material').textContent).toContain('A very long document title')
})
