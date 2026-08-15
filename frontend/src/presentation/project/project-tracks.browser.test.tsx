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
import { MATERIAL_TABS, ProjectView } from './ProjectView.tsx'
import { PROJECT_TRACKS } from './use-project-panes.ts'

/** How the project page's sidebar and content region are sized, and where each
 *  stops being usable — first measured on 2026-08-14, re-measured on
 *  2026-08-15 when the page became a sidebar over one content area.
 *
 * **Two regions, where this file was written against three.** HOLDER is a tab
 * in MATERIAL now, so its floor is gone from `PROJECT_TRACKS` and its content
 * is reached through `MATERIAL_TABS`. `use-project-panes.ts` carries what
 * survived and `ProjectView.tsx`'s `regionOf` carries why.
 *
 * **The fixture is the point of this file, not its setup.** The docstring being
 * settled here deferred to "the slice that gives each region its real content",
 * because a floor measured against empty regions is a floor for the fixture. So
 * QUEUE holds four stages and four topics, and MATERIAL holds a scrub bar over
 * an eight-message transcript, six documents, and a twelve-node graph with the
 * real `GraphCanvas` mounted. Claims 4 and 5 exist to fail if any of that
 * quietly empties — two claims rather than one because the documents and the
 * transcript are two tabs, and only one of them is `keepMounted`.
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
 * content reports a 1px difference often enough to matter. It is also why each
 * floor is a pixel or two above what measured clean rather than equal to it —
 * 343px of QUEUE clears the check only by consuming that slack, which is not
 * clearance.
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
  kind: 'text',
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
  // **Not the Event log, which this waited on until the holding session became
  // a tab.** `Tabs` renders only the active panel, so that region exists only
  // when the session tab is the open one — every `show({ facet: 'doc' })` and
  // `show({ facet: 'entity' })` below would wait fifteen seconds for a region
  // the page is correct not to have.
  //
  // Two waits rather than one, because either alone admits a half-loaded page:
  // the tab strip is chrome and renders before any request resolves, and the
  // topic rows are data. Together they mean "MATERIAL is mounted and QUEUE has
  // its content", which is the precondition every floor below is measured
  // under. Each claim that needs a *particular* panel loaded still waits for it
  // itself — the graph canvas in claim 1, the document title in claim 4.
  await expect.element(page.getByRole('tablist', { name: 'Material' })).toBeVisible()
  await expect
    .poll(() => pane('queue').querySelectorAll('.ent-topic-question').length)
    .toBeGreaterThan(0)
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
})

/** Claim 2. The sidebar is a quarter of the window until its floor takes over,
 *  and MATERIAL is the rest at every width.
 *
 * This claim replaces "the floors bind at 1181 and 1440 is left alone", which
 * was the right claim about three peers sharing free space and is not a claim
 * about a sidebar. `max: '25%'` is not a share of what the floors left over --
 * it is a fraction of the column box itself, so it holds its proportion at
 * every width instead of drifting with its neighbours' content.
 *
 * The crossover is arithmetic and is worth stating because it is where the two
 * rules trade places: 25% of the viewport equals QUEUE's 344px floor at
 * 344/0.25 = 1376. Above that the percentage governs and the sidebar grows with
 * the window; below it the floor governs and the sidebar stops shrinking while
 * MATERIAL absorbs the loss. Both sides are measured below rather than only the
 * ends, because a rule that changed at some *other* width would still satisfy
 * assertions taken at 1181 and 1440 alone.
 *
 * The numbers, measured in Chromium on 2026-08-15:
 *
 * | viewport | queue | material | which rule |
 * | --- | --- | --- | --- |
 * | 1181 | 344 | 837 | floor |
 * | 1376 | 344 | 1032 | floor, exactly at the crossover |
 * | 1440 | 360 | 1080 | 25% |
 *
 * **Proved red** with `max: '25%'` replaced by `weight: 1`: 1440 reads
 * `q=720 m=720`, so `expected 720 to be 360` -- two equal columns, which is
 * what an fr weight means and is the layout this slice replaced.
 */
it('holds the sidebar at a quarter, and at its floor below the crossover', async () => {
  await show()

  await resizeViewport(BP_WIDE)
  // Below the crossover: 25% of 1181 is 295, under QUEUE's 344 floor, so the
  // floor wins and MATERIAL takes everything else.
  expect(Math.round(width('queue'))).toBe(344)
  expect(Math.round(width('material'))).toBe(837)

  await resizeViewport(1440)
  // Above it: exactly a quarter and exactly three quarters. The two assertions
  // together are what make this a sidebar rather than a wide-ish first column —
  // either number alone is satisfied by several other rules.
  expect(Math.round(width('queue'))).toBe(360)
  expect(Math.round(width('material'))).toBe(1080)

  await resizeViewport(1376)
  // The crossover itself, where 25% and the floor are the same number. Asserted
  // because it is the width at which a wrong rule would first disagree with a
  // right one, and neither end catches that.
  expect(Math.round(width('queue'))).toBe(344)
  expect(Math.round(width('material'))).toBe(1032)
})

/** Claim 3. MATERIAL's floor is its tab strip, and the tab strip is a product
 *  constant rather than a fixture.
 *
 * The one region whose floor nothing about the data can move: seven tabs whose
 * labels are declared in `ProjectView.tsx`'s `MATERIAL_TABS`, in a `.tabs` row
 * with no wrap and no scroller. Asserted as "the floor covers the strip" rather
 * than as "the strip is 536px", because that number is a font measurement and
 * would go red on a label edit for the wrong reason. What must hold is that
 * `PROJECT_TRACKS`'s floor is at least what the strip needs.
 *
 * This is the assertion that catches an eighth tab: a label arriving without
 * the floor moving fails here, at the width where it starts costing a reader a
 * tab. It caught the seventh — `expected 422 to be greater than or equal to
 * 536.3125` — which is how this slice learned that adding the holding session
 * to the strip had invalidated a floor measured against six.
 *
 * **The strip is summed rather than read from `scrollWidth`, and that change is
 * load-bearing rather than stylistic.** `scrollWidth` is the larger of the
 * content and the box, so it only reveals the content's width while the content
 * *overflows*. MATERIAL is now three quarters of the page — 837px at the
 * narrowest wide viewport, against a strip needing 536 — so the strip never
 * overflows and `scrollWidth` reports the pane. The old assertions would have
 * compared 837 against 837 and 422 against 837: one vacuously true, the other
 * red for a reason that has nothing to do with tabs. Summing the laid-out
 * children measures the strip whether or not it happens to be cramped.
 */
it('keeps MATERIAL wide enough for the tab strip it always has', async () => {
  await show()
  await resizeViewport(BP_WIDE)

  const strip = pane('material').querySelector<HTMLElement>('.tabs')!
  const style = getComputedStyle(strip)
  const children = [...strip.children].map((tab) => tab.getBoundingClientRect().width)
  const needed =
    children.reduce((total, each) => total + each, 0) +
    Number.parseFloat(style.columnGap || '0') * Math.max(0, children.length - 1) +
    Number.parseFloat(style.paddingLeft || '0') +
    Number.parseFloat(style.paddingRight || '0')

  // Every declared tab is laid out, so a strip that silently lost one cannot
  // pass this by needing less room. `MATERIAL_TABS` is the declaration; this is
  // the only place the two are compared.
  expect(children).toHaveLength(MATERIAL_TABS.length)
  expect(needed).toBeGreaterThan(300)
  expect(width('material')).toBeGreaterThanOrEqual(needed)

  const floor = PROJECT_TRACKS.find((track) => track.id === 'material')!.min
  expect(floor).toBeGreaterThanOrEqual(needed)
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
it('measures a page with both regions loaded', async () => {
  await show({ facet: 'doc', id: null })
  await resizeViewport(BP_WIDE)

  // QUEUE: the topic queue, populated. The stage rail is beside it and is what
  // `ProjectView.browser.test.tsx` already covers.
  expect(pane('queue').querySelectorAll('.ent-topic-question').length).toBeGreaterThan(0)
  // MATERIAL: the documents the Documents tab is open on.
  expect(pane('material').textContent).toContain('A very long document title')
})

/** Claim 5. The transcript is still laid out, one tab away.
 *
 * Separate from claim 4 rather than folded into it, because the two need
 * *different pages*. Claim 4 opens the Documents tab, and this panel is
 * `keepMounted`, so it is still in the tree there — but `hidden`, which is
 * `display: none`, so everything in it measures zero. Folded together, "the
 * transcript is laid out" would be asserted against a panel that is present
 * and zero-sized, which is a green that means nothing.
 *
 * This is the fixture half of the holding session's move into MATERIAL: the
 * conversation used to be its own column and is now the default tab, so "the
 * transcript has messages laid out in it" is still a precondition of every
 * floor above, just reached differently.
 */
it('lays out the transcript in the tab that replaced HOLDER', async () => {
  await show()
  await resizeViewport(BP_WIDE)

  expect(
    pane('material').querySelectorAll('[aria-label="Conversation"] .conv-scroll *').length,
  ).toBeGreaterThan(0)
})
