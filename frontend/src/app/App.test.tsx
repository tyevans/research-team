import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { ApiError } from '@application/ports/errors.ts'
import type { DocumentRepository } from '@application/ports/repositories.ts'
import { emptyExtractionQueue } from '@domain/research/extraction-queue.ts'
import type { MediaSummary } from '@domain/research/document.ts'
import { ComponentId, ProjectId, SessionId, SourceId } from '@domain/shared/identifier.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'
import { parseRoute, projectHref } from '@presentation/routing/routes.ts'

import { App, viewNameOf } from './App.tsx'

/** The application, rendered as the application.
 *
 * There was no test in this file at all until the shell moved onto `Shell`,
 * and the gap was not academic. Every overlay in the console is tested through
 * a harness that supplies its own `OverlayHost` -- `TreeView.test`,
 * `Drawer.test`, `WorkerDrawer.test`, `AgentWidget.test`, four more -- each
 * with a comment saying "in the application this comes from `Shell`". The
 * application did not use `Shell`. It rendered its own `<header>`/`<main>`,
 * mounted no host, and `Overlay` returns `null` without one, so **every
 * drawer, confirm, document reader and the agent dock's popover rendered
 * nothing in the shipped console** while forty-odd tests of those same
 * overlays passed.
 *
 * That is the shape of the hole rather than a story about one bug: a component
 * test cannot see a provider the component does not mount, and the composition
 * root is the one file no component test renders. So this file renders it, and
 * exercises the parts that only exist once it is composed.
 */

const ATLAS = ProjectId('11111111-1111-1111-1111-111111111111')
const HOLDER = SessionId('3f2a0000-0000-0000-0000-000000000000')

const NOW = Date.parse('2026-08-09T12:00:00Z')

/** Two stages, because a deep link to one is only interesting if the other
 *  stays shut. */
const COURSE = {
  projectId: ATLAS,
  projectName: 'atlas',
  holdingSessionId: null,
  preset: { id: 'hybrid.default', name: 'Hybrid', version: '1' },
  position: 1,
  stageCount: 2,
  stages: [
    {
      index: 1,
      id: 'step0.intake',
      name: 'Intake',
      kind: 'author',
      spine: 0,
      scopeLevel: 'course',
      status: 'done',
      outputs: [],
      gateDecisions: [],
      reviewerRole: null,
      findingsReport: null,
    },
    {
      index: 2,
      id: 'step1.framing',
      name: 'Framing',
      kind: 'author',
      spine: 0,
      scopeLevel: 'course',
      status: 'current',
      // One artifact and one finding, so that the three route ids MATERIAL
      // carries have something to land on. Every test above asserts on rail
      // rows, tabs and regions and none of them can see these two.
      outputs: [
        {
          path: 'course/framing/objectives.md',
          artifactType: 'objectives',
          subtype: null,
          cardinality: 'one',
          stageId: 'step1.framing',
          present: true,
          hasFrontmatter: true,
          missingFields: [],
          bodyChars: 100,
          provenance: null,
        },
      ],
      gateDecisions: [],
      reviewerRole: null,
      findingsReport: null,
    },
  ],
  findings: [
    {
      check: 'objectives.count',
      severity: 'advisory',
      message: 'Three objectives is thin for a course this long.',
      suggestedEdit: null,
      cites: [],
    },
  ],
  unimplementedChecks: [],
}

/** The spy the interaction-log assertions read, rebuilt per container so one
 *  test cannot see another's events. Absent entirely until this round: every
 *  test in this file ran the shipped app with `sink === undefined`, and
 *  survived only because `emitter.flushOnUnload` catches. */
let interactions = { send: vi.fn(), sendOnUnload: vi.fn() }

const containerWith = (over: Record<string, unknown> = {}) =>
  ({
    now: () => NOW,
    interactions,
    preferences: new InMemoryPreferenceStore(),
    // Connects and disconnects, delivers nothing. Every frame-driven refresh
    // in the shell is a subscription on this, so a container without it fails
    // in `StreamProvider`'s effect rather than anywhere informative.
    stream: { connect: vi.fn(), disconnect: vi.fn() },
    sessions: {
      list: vi.fn().mockResolvedValue([
        {
          id: SessionId('3f2a1111-1111-1111-1111-111111111111'),
          projectId: ATLAS,
          startedAt: '2026-08-09T09:00:00Z',
          turns: 0,
          files: 0,
          firstMessage: null,
          forkedFrom: null,
          forkedAt: null,
          failedTurns: 0,
        },
      ]),
      tree: vi.fn().mockResolvedValue([]),
    },
    projects: {
      list: vi.fn().mockResolvedValue([
        {
          id: ATLAS,
          name: 'atlas',
          activeSessionId: HOLDER,
          tipAtEvent: 0,
          workflow: null,
          stage: null,
        },
      ]),
      presets: vi.fn().mockResolvedValue([]),
      create: vi.fn(),
      chooseWorkflow: vi.fn(),
      course: vi.fn().mockResolvedValue(COURSE),
      join: vi.fn(),
      delete: vi.fn().mockResolvedValue(undefined),
    },
    research: { current: vi.fn().mockResolvedValue(null) },
    workers: {
      on: vi.fn().mockResolvedValue({
        projectId: ATLAS,
        workers: [
          { ref: 'w1', kind: 'turn', detail: 'answering', sessionId: HOLDER, parentRef: null },
        ],
        idleSessionIds: [],
      }),
      everywhere: vi.fn().mockResolvedValue([]),
    },
    extractions: { on: vi.fn().mockResolvedValue({ current: [], last: [] }) },
    // The research view's own reads. Quiet, because which view the facet
    // reached is the question and none of these answers it.
    topics: { queue: vi.fn().mockResolvedValue([]), open: vi.fn() },
    documents: { list: vi.fn().mockResolvedValue([]) },
    graphs: {
      whole: vi.fn().mockResolvedValue({
        entities: [],
        relationships: [],
        truncated: false,
        inferredTruncated: false,
      }),
      neighborhood: vi.fn().mockResolvedValue({ entities: [], relationships: [] }),
      search: vi.fn().mockResolvedValue({ entities: [], types: [] }),
    },
    // The Curriculum tab is now the default (`DEFAULT_MATERIAL`), so every
    // project render in this file mounts `CatalogPane`, which reads these two
    // ports. An empty catalog rather than a rejecting stub: a rejection paints
    // `ErrorBox`, and an error page is not what the tests below mean by "the
    // default tab opened".
    //
    // **Checked field by field against `Catalog`, `BlurbSweepProgress` and
    // `ArtSweepProgress` by hand**, because `containerWith` ends in an `as
    // unknown as AppContainer` and the compiler checks nothing here. One stub
    // in this object carried a wrong field name for over a month on exactly
    // that cast.
    catalog: {
      catalog: vi.fn().mockResolvedValue({
        sections: { hero: [], highlights: [], filed: [] },
        categories: new Map<string, string>(),
        unplaceableFeatured: [],
        unnamedCount: 0,
        orphanedCourses: [],
        derivedFrom: { entities: 0, relationships: 0 },
      }),
      feature: vi.fn(),
      unfeature: vi.fn(),
    },
    courses: {
      course: vi.fn(),
      courseText: vi.fn(),
      realize: vi.fn(),
      abandon: vi.fn(),
      startBlurbSweep: vi.fn(),
      fetchBlurbSweep: vi
        .fn()
        .mockResolvedValue({ running: false, done: 0, total: 0, failed: 0, error: null }),
      startArtSweep: vi.fn(),
      fetchArtSweep: vi
        .fn()
        .mockResolvedValue({ running: false, done: 0, total: 0, failed: 0, error: null }),
      startArtReroll: vi.fn(),
      fetchArtReroll: vi.fn(),
    },
    health: {
      summaries: vi.fn().mockResolvedValue({ healthy: true, following: true, failedEvents: 0 }),
      rebuildSummaries: vi.fn(),
    },
    ...over,
  }) as unknown as AppContainer

const renderApp = (container: AppContainer = containerWith()) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  // No `OverlayHost` here, and that is the point of the file: if one is needed
  // to make an overlay appear, the application is missing it too.
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>{children}</ContainerProvider>
    </QueryClientProvider>
  )
  return render(<App />, { wrapper })
}

beforeEach(() => {
  window.location.hash = ''
  interactions = { send: vi.fn(), sendOnUnload: vi.fn() }
})

it('renders one main landmark, with the chrome outside it', async () => {
  renderApp()

  // `Shell` promises exactly one `main` per page and puts the chrome above it.
  // Asserted through roles rather than class names so it keeps holding if the
  // stylesheet is rewritten -- which phase 5 will do.
  const main = await screen.findByRole('main')
  const banner = screen.getByRole('banner')
  expect(within(banner).getByRole('link', { name: /research/i })).toBeInTheDocument()
  expect(banner).not.toContainElement(main)
  expect(screen.getAllByRole('main')).toHaveLength(1)
})

it('opens a dialog, which needs the overlay host the shell mounts', async () => {
  // Reverted to the hand-built `<header>`/`<main>` this test fails here: the
  // menu opens, `Delete` sets the pending confirmation, `Confirm` renders an
  // `Overlay`, and `Overlay` with no host in scope returns `null`. Nothing
  // else in the repository fails, because every other test of this dialog
  // brings its own host.
  const user = userEvent.setup()
  renderApp()

  await user.click(await screen.findByRole('button', { name: /More actions for atlas/ }))
  // `findByRole`, and `menuitem` rather than `button`. Both changed with the
  // row menu: a `Disclosure` opened synchronously inside the click's own act
  // and held plain `<button>`s, where `Menu` portals its content through
  // Radix's presence and gives each item `role="menuitem"`. A synchronous
  // `getByRole` here found nothing.
  await user.click(await screen.findByRole('menuitem', { name: 'Delete' }))

  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveAttribute('aria-modal', 'true')
  expect(within(dialog).getByText(/cannot rejoin/)).toBeInTheDocument()
})

it('opens the stage a link named, rather than loading collapsed', async () => {
  // The point of the `stage` facet, and the fix for a course page that always
  // loaded fully collapsed: `openStage` was `useCourse`'s `useState`, so the
  // only way to see a stage's body was to click it, and "the stage whose gate
  // is blocking this project" could not be sent to anybody.
  //
  // Asserted through `aria-expanded` on the two rail rows rather than through
  // the prop, because a route that reached `CourseView` and did not reach
  // `StageList` is the failure worth catching, and the prop cannot see it.
  window.location.hash = `#/p/${ATLAS}/stage/step1.framing`
  renderApp()

  const framing = await screen.findByRole('button', { name: /Framing/ })
  expect(framing).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByRole('button', { name: /Intake/ })).toHaveAttribute('aria-expanded', 'false')
})

it('puts a clicked stage in the address bar without a history entry', async () => {
  // Replaced rather than pushed, which is the answer to the objection
  // `useCourse` used to raise against routing this at all: linkable, and forty
  // glances still leave the back button pointing where the reader came from.
  const user = userEvent.setup()
  window.location.hash = `#/p/${ATLAS}`
  renderApp()

  const before = window.history.length
  await user.click(await screen.findByRole('button', { name: /Framing/ }))

  expect(window.location.hash).toBe(`#/p/${ATLAS}/stage/step1.framing`)
  expect(window.history.length).toBe(before)
})

it('gives one project route a sidebar and a content region, not a choice of two pages', async () => {
  // The merge, seen from the route: every project facet lands on the same page.
  // Reverted, this fails on the first assertion -- there was no `Project
  // regions` group, because there was no container, and `#/p/<id>/entity/e1`
  // reached a whole separate view whose heading said "Research".
  //
  // **Two regions, where this said three until the sidebar slice.** HOLDER was
  // a region and is now a tab inside MATERIAL, so "Holding session" is no
  // longer a region name and asking for one would pass on a `tablist` label if
  // this used a loose query. `region` is the strict one: it matches the
  // `<section aria-label>` a `Pane` renders and nothing else.
  window.location.hash = `#/p/${ATLAS}/entity/e1`
  renderApp()

  expect(await screen.findByRole('group', { name: 'Project regions' })).toBeInTheDocument()
  for (const region of ['Queue', 'Material']) {
    expect(screen.getByRole('region', { name: region })).toBeInTheDocument()
  }
  expect(screen.queryByRole('region', { name: 'Holding session' })).toBeNull()
})

it('reaches the material region for a facet that used to reach nothing', async () => {
  // `artifact` parsed and was linkable and no view read it: it fell through
  // `RESEARCH_FACETS` onto the course page, which renders nothing about an
  // artifact selection. Asserted through the open tab rather than through the
  // region, because a page that mounted MATERIAL and ignored the facet would
  // satisfy the test above.
  window.location.hash = `#/p/${ATLAS}/artifact/objectives.md`
  renderApp()

  expect(await screen.findByRole('tab', { name: 'Artifacts', selected: true })).toBeInTheDocument()
})

it('keeps ask a view of its own rather than a region', async () => {
  // The one arm of the old dispatch that survives, and the reason is in
  // `regionOf`: the ask page is one conversation with no parts and nothing to
  // read it against. A merge that swept it in with the rest would put a
  // conversation in a third of a column beside two regions it cannot use.
  window.location.hash = `#/p/${ATLAS}/ask`
  renderApp()

  await waitFor(() =>
    expect(screen.queryByRole('group', { name: 'Project regions' })).not.toBeInTheDocument(),
  )
})

/** A route with no way in is a deleted feature, and this one was deleted for a
 *  slice without anybody noticing.
 *
 * `#/p/<id>/ask` has routed, rendered and worked throughout — the test above
 * proves it, and it passed on every commit. What went missing was the *door*:
 * the only two links to it lived in `CourseView` and `ResearchView`'s heading
 * rows, and slice 1 deleted both views. The ask page even links back to the
 * project, so for one slice a reader could leave it and never return.
 *
 * That is why this asserts an inbound link from the project page rather than
 * another render of the ask route. Every test in this file navigates by
 * assigning `window.location.hash`, which is exactly the ability a reader does
 * not have — a suite that only ever teleports cannot notice that the stairs are
 * gone.
 *
 * **Proved red** by removing the link from `QueueHeader`: `Unable to find an
 * accessible element with the role "link" and name /ask this project/i`.
 */
it('offers a way into the ask page from the project page', async () => {
  window.location.hash = `#/p/${ATLAS}`
  renderApp()

  const link = await screen.findByRole('link', { name: /ask this project/i })
  expect(link).toHaveAttribute('href', `#/p/${ATLAS}/ask`)
})

/** The same failure, one plan later, on the surface built by the plan that
 *  quoted the comment above.
 *
 * `facet: 'dialogue'` had **zero** `projectHref` call sites where `facet:
 * 'ask'` has three: the page routed, rendered, streamed and graded, and the
 * only way to reach it was to type `#/p/<id>/dialogue` into the address bar.
 * Nothing was red, because nothing in this suite navigates the way a reader
 * does -- every other test here assigns `window.location.hash`.
 *
 * **Proved red** on 2026-08-18 by reverting the link in `QueueHeader`: `Unable
 * to find an accessible element with the role "link" and name /be asked about
 * this project/i`.
 */
it('offers a way into the dialogue page from the project page', async () => {
  window.location.hash = `#/p/${ATLAS}`
  renderApp()

  const link = await screen.findByRole('link', { name: /be asked about this project/i })
  expect(link).toHaveAttribute('href', `#/p/${ATLAS}/dialogue`)
})

it('hands the selected entity to the graph, not just the view', async () => {
  // The id has to survive the facet, not only the route: a dispatch that
  // reached `ResearchView` with `entity` hard-null would satisfy the test
  // above and draw the wrong graph.
  const neighborhood = vi.fn().mockResolvedValue({ entities: [], relationships: [] })
  window.location.hash = `#/p/${ATLAS}/entity/e1`
  renderApp(
    containerWith({
      graphs: {
        whole: vi.fn().mockResolvedValue({
          entities: [],
          relationships: [],
          truncated: false,
          inferredTruncated: false,
        }),
        neighborhood,
        search: vi.fn().mockResolvedValue({ entities: [], types: [] }),
      },
    }),
  )

  await waitFor(() => expect(neighborhood).toHaveBeenCalledWith(ATLAS, 'e1'))
})

/** The three MATERIAL facets that parsed an id, reached the right tab, and then
 *  dropped it.
 *
 * `App.test.tsx` already asserted that `#/p/<id>/artifact/<path>` opens the
 * Artifacts tab, and that assertion is satisfied by a page that mounts MATERIAL
 * and ignores the facet entirely — which is exactly what shipped. `topic`,
 * `doc`, `artifact` and `finding` each held their open item in a component's
 * own `useState`, so the id reached the tab and stopped there. The `doc` half
 * was a live broken link: `CitationList` writes `#/p/<id>/doc/<sourceId>` and
 * following it produced an unfiltered corpus.
 *
 * Asserted through `aria-current` on the row, for the reason the stage test
 * above asserts through `aria-expanded`: the prop cannot see a route that
 * reached the page and not the list.
 *
 * `topic` is deliberately not here — it is QUEUE's, slice 3 did not rewrite it,
 * and it is still `useState` in `use-topic-queue.ts`. */
it('marks the artifact the route names, not merely the tab it lives in', async () => {
  // Built rather than hand-typed: an artifact id is a path, and the grammar
  // keeps it in one segment by percent-encoding the slashes. A literal
  // `/artifact/course/framing/...` parses the id as `course`.
  window.location.hash = projectHref(ATLAS, {
    facet: 'artifact',
    id: 'course/framing/objectives.md',
  })
  renderApp()

  // `closest('[aria-current]')` rather than `getByRole('listitem', {current})`:
  // the row is found through the text a reader sees, and the marking is then
  // asserted on the element that carries it. The role query would work too and
  // would depend on a testing-library option version rather than on the DOM.
  const name = await screen.findByText('objectives.md')
  expect(name.closest('li')).toHaveAttribute('aria-current', 'true')
})

it('marks the finding the route names', async () => {
  // Matched on the check name, which is the only stable id a finding has: the
  // array index is not, because the list is recomputed against a growing
  // course.
  window.location.hash = projectHref(ATLAS, { facet: 'finding', id: 'objectives.count' })
  renderApp()

  await screen.findByRole('tab', { name: 'Findings', selected: true })
  const message = await screen.findByText(/thin for a course/)
  expect(message.closest('li')).toHaveAttribute('aria-current', 'true')
})

it('puts a watched worker in the address bar under the session facet', async () => {
  // The drawer's session used to be `#/p/<id>/course/watching/<sid>`, a segment
  // pair that existed for this one case. It is the `session` facet now, which
  // is the same grammar `#/s/<sid>` and every other selection use -- and this
  // is the only test in the repository that sees which one is written, because
  // `Workers` takes `onWatch` as a prop and never builds an href.
  const user = userEvent.setup()
  window.location.hash = `#/p/${ATLAS}`
  renderApp()

  const worker = await screen.findByRole('button', { name: 'answering' })
  expect(worker).toHaveAttribute('aria-pressed', 'false')

  await user.click(worker)

  expect(window.location.hash).toBe(`#/p/${ATLAS}/session/${HOLDER}`)
  // Read back *off the route*, not held beside it. A view that kept its own
  // copy would light this row up on a hash it never wrote, and a reload would
  // then close a drawer the URL still names.
  // `hidden: true` because watching also opens the transcript drawer, which is
  // modal — the roster behind it is correctly hidden from the accessibility
  // tree, and it is still the thing under assertion.
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'answering', hidden: true })).toHaveAttribute(
      'aria-pressed',
      'true',
    ),
  )
})

const MEDIA = SourceId('m1')

const media = (over: Partial<MediaSummary> = {}): MediaSummary => ({
  sourceId: MEDIA,
  kind: 'media',
  mediaType: 'video/mp4',
  byteCount: 12_500_000,
  sha256: 'deadbeef',
  uri: null,
  title: 'The keynote',
  publishedAt: null,
  note: null,
  fetchedAt: null,
  droppedReason: null,
  extracted: false,
  ...over,
})

const fakeDocumentsWithMedia = (): DocumentRepository => ({
  list: vi.fn().mockResolvedValue([media()]),
  read: vi.fn(() => {
    throw new Error('read must not be called for media')
  }),
  extract: vi.fn(),
  extractAll: vi.fn(),
  extractionQueue: vi.fn().mockResolvedValue(emptyExtractionQueue),
  cancelExtraction: vi.fn(),
  perceive: vi.fn(),
  create: vi.fn(),
  revise: vi.fn(),
  drop: vi.fn(),
  restore: vi.fn(),
  contentUrl: (projectId, sourceId) => `/api/projects/${projectId}/sources/${sourceId}/content`,
  uploadMedia: vi.fn(),
})

/** The seam this task exists to close: `GraphDetail` puts `?t=252` on a
 *  citation link, and until this test the whole path from that URL to a
 *  seeked player had never been exercised together -- `DocumentReader`'s own
 *  tests pass `seekSeconds` as a prop, which proves the component but not
 *  that anything upstream ever supplies it. Rendering `App` and setting
 *  `window.location.hash` the way a followed link would is what makes this
 *  end-to-end rather than a second unit test of the same prop.
 *
 * It also stands in for the router risk raised while wiring this: a query
 * string glued onto the last path segment (`wouter`'s `useHashLocation`
 * does not strip it) could easily have corrupted the document id instead of
 * being read as a seek. This passing is what confirms `doc/<id>?t=252` still
 * resolves to `<id>`, not `<id>?t=252`. */
it('seeks a cited video to the second a `?t=` query names, on a followed link', async () => {
  window.location.hash = `#/p/${ATLAS}/doc/${MEDIA}?t=252`
  renderApp(containerWith({ documents: fakeDocumentsWithMedia() }))

  const player = await screen.findByTestId('media-player')
  expect((player as HTMLMediaElement).currentTime).toBe(252)
})

// The falsy trap, exercised at the top of the stack: a citation at a
// source's first second is real, and any `if (seekSeconds)` guard between
// the query string and `currentTime` would silently swallow it.
it('seeks to second zero rather than treating the query as absent', async () => {
  window.location.hash = `#/p/${ATLAS}/doc/${MEDIA}?t=0`
  renderApp(containerWith({ documents: fakeDocumentsWithMedia() }))

  const player = await screen.findByTestId('media-player')
  expect((player as HTMLMediaElement).currentTime).toBe(0)
})

// The ordinary case, and the majority one: most links into a document carry
// no `?t=` at all, and the player must not seek anywhere on its own.
it('does not seek an opened document with no `?t=` in its link', async () => {
  window.location.hash = `#/p/${ATLAS}/doc/${MEDIA}`
  renderApp(containerWith({ documents: fakeDocumentsWithMedia() }))

  const player = await screen.findByTestId('media-player')
  expect((player as HTMLMediaElement).currentTime).toBe(0)
})

/** A dialogue that survives being left and come back to -- the whole chain, in
 *  one test, because the plan that built it had six tasks and a review apiece
 *  and none of them owned this.
 *
 * Every hop was correct and separately proved: the route,
 * `dialogue_progress_view`, `dialogueProgressDto`, `toDialogueProgress`, the
 * four-hop prop chain, and the keying by the turn's position. Nothing wrote the
 * minted id into the hash, so `DialogueView` began every mount at
 * `dialogueId: null`, `refreshProgress` short-circuited on its own guard, and
 * the only dialogue reachable in a browser was one just minted with no attempts
 * in it. `progress` could therefore only ever be `{}` on a real screen: a
 * refresh did not lose the grades, it lost the dialogue.
 *
 * So this asserts the chain and not a hop of it -- a dialogue started, its id in
 * the URL, a REMOUNT that reads it back, and a recorded attempt arriving as
 * `stored` on the widget. Proved red against the code before this fix at the
 * hash assertion, and red again at the composer's label with the navigation put
 * back and the seed left out -- both measured, not reasoned.
 *
 * Here rather than beside the dialogue components for this file's reason: the
 * composition root is the one file a component test never renders, and the
 * missing wiring was in it.
 */
const DIALOGUE = 'd7c1e3aa-0000-4000-8000-000000000007'

const fakeDialogues = () => ({
  start: vi.fn().mockResolvedValue({
    dialogueId: DIALOGUE,
    goal: 'understand what the creed settled',
    stoppingCondition: 'the reader explains it unaided',
    openingBlocks: [{ kind: 'markdown', text: 'Where would you start?' }],
  }),
  // One turn's worth of marked answers, keyed the way the server keys them.
  progress: vi.fn().mockResolvedValue({
    'turn/0': new Map([
      [
        ComponentId('council-1'),
        { attempts: 2, correct: true, bestScore: 1, lastScore: 1, checked: [] },
      ],
    ]),
  }),
  // Answers with the question the reply produced, carrying the component the
  // progress above was recorded against. `position: 0` is the turn's, off the
  // frame -- not its index.
  reply: vi.fn(
    async (
      _projectId: unknown,
      _dialogueId: unknown,
      _reply: string,
      onEvent: (event: unknown) => void,
    ) => {
      onEvent({
        type: 'prompt',
        blocks: [componentBlock({ type: 'mcq', id: 'council-1' })],
        position: 0,
        citations: [],
        concluded: false,
      })
    },
  ),
  submitDialogueAttempt: vi.fn(),
})

it('puts a started dialogue in the URL, and finds its answers again after a remount', async () => {
  const user = userEvent.setup()
  const dialogues = fakeDialogues()
  const container = containerWith({ dialogues })
  window.location.hash = `#/p/${ATLAS}/dialogue`
  const first = renderApp(container)

  await user.type(await screen.findByLabelText('Topic'), 'the creed')
  await user.click(screen.getByRole('button', { name: 'Start' }))

  // The hop that did not exist. Replaced rather than pushed: `.../dialogue`
  // with nothing after it is the blank composer the reader just left.
  await waitFor(() => {
    expect(window.location.hash).toBe(`#/p/${ATLAS}/dialogue/${DIALOGUE}`)
  })

  // The refresh, as a reader performs it: the page goes away and comes back at
  // the URL that is now in the address bar.
  first.unmount()
  renderApp(container)

  // Seeded from the URL, which is the half of the fix the navigation alone
  // does not buy: the composer asks for an answer rather than for a topic,
  // because there is already a dialogue here.
  expect(await screen.findByLabelText('Your answer')).toBeInTheDocument()
  await waitFor(() => {
    expect(dialogues.progress).toHaveBeenCalledWith(ATLAS, DIALOGUE)
  })

  await user.type(screen.getByLabelText('Your answer'), 'It settled Arianism.')
  await user.click(screen.getByRole('button', { name: 'Answer' }))

  // The far end of the chain: a verdict recorded before the remount, drawn on
  // the widget. The sentence a reader sees, not a prop.
  expect(
    await screen.findByText(/you answered this correctly after 2 tries before/i),
  ).toBeInTheDocument()
})

/** The interaction log, seen from the composition root.
 *
 * Deleting the `<InteractionLogProvider>` wrapper from `App.tsx` left all 15
 * tests above green and all 4 provider tests green, and the console collected
 * nothing -- which is the exact state the commit that added the wrapper says it
 * is fixing. Same hole this file was written for: no component test renders the
 * composition root, so no component test can see a provider it fails to mount.
 * Proved red by replacing the wrapper with a fragment -- the batch comes back
 * undefined, because nothing calls `sendOnUnload` at all. */
it('mounts the interaction log over the application, not merely beside it', async () => {
  window.location.hash = `#/p/${ATLAS}/entity/e1`
  const { unmount } = renderApp()
  await screen.findByRole('group', { name: 'Project regions' })

  unmount()
  // The provider's teardown defers its final beacon by a microtask so a
  // StrictMode remount can cancel it; nothing has reached the sink until then.
  await Promise.resolve()

  const batch = interactions.sendOnUnload.mock.calls[0]?.[0] as
    { kind: string; view: string; project_id: string | null }[] | undefined
  expect(
    batch?.some(
      (event) =>
        event.kind === 'ViewEntered' &&
        event.view === 'project/entity' &&
        event.project_id === ATLAS,
    ),
  ).toBe(true)
})

/** `ProjectSwitched`, seen the same way -- from the composition root, since
 *  `ProjectSwitchLog`'s own comment says why it cannot be a plain hook test:
 *  it has to sit inside the provider `Console` renders, not beside it. */
it('records ProjectSwitched when the route moves from one project to another', async () => {
  const OTHER = ProjectId('22222222-2222-2222-2222-222222222222')
  window.location.hash = `#/p/${ATLAS}`
  const { unmount } = renderApp()
  await screen.findByRole('group', { name: 'Project regions' })

  window.location.hash = `#/p/${OTHER}`
  await screen.findByRole('group', { name: 'Project regions' })

  unmount()
  await Promise.resolve()

  const batch = interactions.sendOnUnload.mock.calls[0]?.[0] as
    | { kind: string; payload: { to_project_id: string; from_project_id: string | null } }[]
    | undefined
  expect(
    batch?.some(
      (event) =>
        event.kind === 'ProjectSwitched' &&
        event.payload.to_project_id === OTHER &&
        event.payload.from_project_id === ATLAS,
    ),
  ).toBe(true)
})

/** The first project a session opens still fires -- there is no project
 *  before it to have switched from, and `from_project_id: null` says exactly
 *  that rather than the event being withheld. "Opened project X" is itself
 *  worth knowing, not only "left X for Y". */
it('records ProjectSwitched with a null from_project_id for the first project the route names', async () => {
  window.location.hash = `#/p/${ATLAS}`
  const { unmount } = renderApp()
  await screen.findByRole('group', { name: 'Project regions' })

  unmount()
  await Promise.resolve()

  const batch = interactions.sendOnUnload.mock.calls[0]?.[0] as
    | { kind: string; payload: { to_project_id: string; from_project_id: string | null } }[]
    | undefined
  expect(
    batch?.some(
      (event) =>
        event.kind === 'ProjectSwitched' &&
        event.payload.to_project_id === ATLAS &&
        event.payload.from_project_id === null,
    ),
  ).toBe(true)
})

/** Navigating within one project -- a facet change, or the same project's
 *  route re-parsed with a different selection -- is not a project switch and
 *  must not fire a second event with the same `to_project_id`. */
it('records no second ProjectSwitched for a facet change inside the same project', async () => {
  window.location.hash = `#/p/${ATLAS}`
  const { unmount } = renderApp()
  await screen.findByRole('group', { name: 'Project regions' })

  window.location.hash = `#/p/${ATLAS}/entity/e1`
  await screen.findByRole('group', { name: 'Project regions' })

  unmount()
  await Promise.resolve()

  const batch = interactions.sendOnUnload.mock.calls[0]?.[0] as { kind: string }[] | undefined
  expect(batch?.filter((event) => event.kind === 'ProjectSwitched')).toHaveLength(1)
})

/** `viewNameOf` had no test at all, and it is the one function deciding what
 *  every row of the log is filed under. Driven through `parseRoute` rather than
 *  hand-built route objects, so a route shape that stops parsing the way this
 *  expects fails here rather than silently renaming a view. */
it.each([
  ['#/', 'home'],
  ['#/nonsense', 'home'],
  [`#/s/${HOLDER}`, 'session'],
  // No selection: the facet is `ProjectView`'s `DEFAULT_MATERIAL`, which
  // `viewNameOf` now imports rather than repeats. It was `project/session`
  // until the default moved to the catalog, and the log's own dwell figures
  // are what moved it -- see `DEFAULT_MATERIAL`.
  [`#/p/${ATLAS}`, 'project/catalog'],
  [`#/p/${ATLAS}/entity/e1`, 'project/entity'],
  [`#/p/${ATLAS}/doc/d1`, 'project/doc'],
  [`#/p/${ATLAS}/ask`, 'project/ask'],
  [`#/p/${ATLAS}/topic/t1`, 'project/topic'],
  [`#/p/${ATLAS}/stage/step1.framing`, 'project/stage'],
  [`#/p/${ATLAS}/timeline`, 'project/timeline'],
  [`#/p/${ATLAS}/artifact/objectives.md`, 'project/artifact'],
  // An unrecognised facet parses as home rather than as a project route, so
  // the log cannot grow a view name nobody chose.
  [`#/p/${ATLAS}/wat`, 'home'],
])('names the view for %s', (hash, expected) => {
  expect(viewNameOf(parseRoute(hash))).toBe(expected)
})

/** The Findings tab, on a project that runs no workflow.
 *
 * Measured against the running console on 2026-08-23: `/api/projects/<Star
 * Trek>/course` answers **409** ("this project runs no workflow, so there is
 * no course to show"), the course query is `retry: false`, and the Findings
 * panel branched on `course.data` alone -- so it rendered `loading findings…`
 * for as long as the tab stayed open. The query had already settled; nothing
 * was in flight and nothing ever would be.
 *
 * Asserted on the rendered *message* rather than on "the panel is not
 * loading": a panel that renders nothing at all would pass the negative and is
 * the same defect wearing a different face. The Queue pane beside it already
 * said "No course to show." the whole time, which is why this was only ever
 * visible one tab at a time.
 */
it('says why the Findings tab has nothing, rather than loading forever', async () => {
  window.location.hash = `#/p/${ATLAS}/finding`
  renderApp(
    containerWith({
      projects: {
        ...(containerWith().projects as object),
        course: vi.fn().mockRejectedValue(new ApiError('this project runs no workflow', 409)),
      },
    }),
  )

  // Scoped to the tab panel, not to the page: the Queue pane beside it renders
  // the very same server message under "No course to show.", so an unscoped
  // `findByText` passes with this panel still stuck on `loading findings…`.
  // The first draft of this test did exactly that.
  // Re-queried inside `waitFor` rather than held: the panel mounts before the
  // course query settles, so a handle taken at the first render is a handle on
  // `loading findings…` and asserting against it is a race the fix loses.
  await waitFor(() =>
    expect(
      within(screen.getByRole('tabpanel', { name: 'Findings' })).getByText(
        /this project runs no workflow/,
      ),
    ).toBeInTheDocument(),
  )
  expect(
    within(screen.getByRole('tabpanel', { name: 'Findings' })).queryByText(/loading findings/),
  ).not.toBeInTheDocument()
})

/** The tab a bare project link opens.
 *
 * **This is the assertion the change is about, and it is deliberately about
 * *which tab is selected* rather than about the page rendering.** "The project
 * page came up" passes with `DEFAULT_MATERIAL` reverted to `session` and with
 * the whole change reverted; it proves the router works and nothing else.
 *
 * Proved red before it was trusted green: with `DEFAULT_MATERIAL` set back to
 * `'session'` this fails on the first line -- `expect(element).toHaveAttribute
 * ("aria-selected", "true")` against `aria-selected="false"` on the Curriculum
 * tab -- and the second line fails too, which is the pair that makes it a
 * statement about *the* default rather than about one tab happening to be on.
 *
 * `catalog` is a facet with no tab of its own, so this is also the test that
 * the default reaches `'area'` through `materialTab`'s mapping. Without that
 * mapping Radix holds a `value` no trigger carries and **no** tab is selected
 * -- which the first line catches and a `queryByRole` on the panel would not.
 */
it('opens a bare project link on the catalog, not the holding session', async () => {
  window.location.hash = `#/p/${ATLAS}`
  renderApp()

  const curriculum = await screen.findByRole('tab', { name: 'Curriculum' })
  expect(curriculum).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('tab', { name: 'Holding session' })).toHaveAttribute(
    'aria-selected',
    'false',
  )
})

/** A project nothing is holding has no workspace, so it is offered no
 *  Workspace tab.
 *
 * `COURSE` above carries `holdingSessionId: null`, which is the condition --
 * a project's files belong to the session holding it, and with none there is
 * no tree to show rather than an empty one. The tab's own panel already said
 * so in an `EmptyState`; what the interaction log measured is that saying so
 * costs a reader a click, 0.7s and a departure, 14 times out of 14.
 *
 * The second assertion is what stops this passing vacuously: a strip that
 * failed to render at all would satisfy the `queryByRole` alone.
 *
 * Reverted -- `TabList` given `MATERIAL_TABS` again -- this fails on the
 * first line, because the trigger is rendered whatever the panel would say. */
it('offers no Workspace tab when nothing is holding the project', async () => {
  window.location.hash = `#/p/${ATLAS}`
  renderApp()

  await screen.findByRole('tab', { name: 'Curriculum' })
  expect(screen.queryByRole('tab', { name: 'Workspace' })).not.toBeInTheDocument()
  expect(screen.getByRole('tab', { name: 'Documents' })).toBeInTheDocument()
})

/** A project that runs no workflow is offered no Artifacts or Findings tab.
 *
 * The same 409 the Findings test above measured against the running console:
 * `/api/projects/<id>/course` answers "this project runs no workflow", the
 * query is `retry: false`, and both panels can only ever say so. There is no
 * `workflow` field on `Course` to test -- the query's own failure *is* the
 * condition, which is why `visibleMaterialTabs` takes `hasCourse` rather than
 * a course.
 *
 * `waitFor`, because the strip is honest about not knowing yet: the tabs are
 * present until the query settles, which is the flicker `DEFAULT_MATERIAL`'s
 * neighbouring docstring chooses over rearranging the strip during every
 * load.
 *
 * Graph is asserted present in the same breath so this cannot pass by the
 * strip having emptied. */
it('offers no Artifacts or Findings tab on a project that runs no workflow', async () => {
  window.location.hash = `#/p/${ATLAS}`
  renderApp(
    containerWith({
      projects: {
        ...(containerWith().projects as object),
        course: vi.fn().mockRejectedValue(new ApiError('this project runs no workflow', 409)),
      },
    }),
  )

  await waitFor(() =>
    expect(screen.queryByRole('tab', { name: 'Artifacts' })).not.toBeInTheDocument(),
  )
  expect(screen.queryByRole('tab', { name: 'Findings' })).not.toBeInTheDocument()
  expect(screen.getByRole('tab', { name: 'Graph' })).toBeInTheDocument()
})

/** A link to a hidden tab still opens it, with its trigger.
 *
 * The alternative was measured against the primitive rather than guessed:
 * Radix selects the trigger whose `value` matches, so a `value` with no
 * trigger leaves **every** tab unselected while the panel below is open --
 * a strip that has visibly lost its place. Somebody sent this link; the
 * honest answer is the tab, selected, saying why it is empty.
 *
 * This is the arm of `visibleMaterialTabs` that takes `openTab`, and it is the
 * one that would rot silently: nothing else in the suite navigates to a tab
 * that the same render has decided to hide.
 *
 * Reverted -- the `tab.id === openTab` line removed -- this fails on the first
 * assertion, and the third would fail too. */
it('keeps a hidden tab that the route explicitly names, and selects it', async () => {
  window.location.hash = `#/p/${ATLAS}/finding`
  renderApp(
    containerWith({
      projects: {
        ...(containerWith().projects as object),
        course: vi.fn().mockRejectedValue(new ApiError('this project runs no workflow', 409)),
      },
    }),
  )

  // Waited on **first**, and the order is the whole test. Every tab is present
  // until the course query settles, so a `findByRole('tab', { name:
  // 'Findings' })` up here resolves against the pre-settle paint and passes
  // with the `openTab` arm deleted entirely -- measured, on the first draft of
  // this test. Artifacts disappearing is the signal that the condition has
  // fired; only after that does "Findings is still here" mean anything.
  await waitFor(() =>
    expect(screen.queryByRole('tab', { name: 'Artifacts' })).not.toBeInTheDocument(),
  )
  const findings = screen.getByRole('tab', { name: 'Findings' })
  expect(findings).toHaveAttribute('aria-selected', 'true')
})
