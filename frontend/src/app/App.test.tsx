import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { DocumentRepository } from '@application/ports/repositories.ts'
import { emptyExtractionQueue } from '@domain/research/extraction-queue.ts'
import type { MediaSummary } from '@domain/research/document.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import { ComponentId, ProjectId, SessionId, SourceId } from '@domain/shared/identifier.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'
import { parseRoute } from '@presentation/routing/routes.ts'

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
/** The session a *released* project's files still fold out of -- its reading
 *  head, which is not its holder because it has none. */
const TIP = SessionId('7c4b0000-0000-0000-0000-000000000000')

const NOW = Date.parse('2026-08-09T12:00:00Z')

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
        },
      ]),
      create: vi.fn(),
      // The breadcrumb's project name, the transcript's session and the
      // Workspace tab all read this now rather than the course. Held by the
      // same session the row above reports, because a container that
      // disagreed with itself would make "the page found the holder" depend
      // on which read answered first.
      project: vi.fn().mockResolvedValue({
        id: ATLAS,
        name: 'atlas',
        activeSessionId: HOLDER,
        tipAtEvent: 0,
      }),
      join: vi.fn(),
      delete: vi.fn().mockResolvedValue(undefined),
    },
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

/** A project **nobody is holding** that nevertheless has files.
 *
 * The state the reading head exists for, and the one no fixture in this file
 * could produce before it: `activeSessionId` is null -- nothing is driving the
 * project -- and `readingHeadSessionId` names the tip session its filesystem
 * folds out of. That is the ordinary resting state of every project between
 * sessions, and until this slice the console showed it as a project with no
 * workspace at all.
 *
 * `sessions.read` and `sessions.log` are stubbed because `SessionStore.open`
 * calls both, and a workspace with no file in it would prove only that the tab
 * exists -- which is the defect the tab was hidden for. One file, named, so
 * the assertion can be that a reader sees it.
 */
const withWorkspace = () => {
  const projection = {
    id: TIP,
    projectId: ATLAS,
    holdsProject: false,
    knowledgeAttached: null,
    modelName: null,
    systemPrompt: null,
    turnIndex: 0,
    failedTurns: 0,
    forkedFrom: null,
    forkedAt: null,
    eventCount: 4,
    compactedThrough: null,
    compactionSummary: null,
    at: null,
    files: [{ path: FilePath.of('/notes.md'), size: 12, revisions: 1 }],
    messages: [],
  }
  return containerWith({
    projects: {
      list: vi.fn().mockResolvedValue([]),
      create: vi.fn(),
      project: vi.fn().mockResolvedValue({
        id: ATLAS,
        name: 'atlas',
        activeSessionId: null,
        tipAtEvent: 4,
        readingHeadSessionId: TIP,
      }),
      join: vi.fn(),
      delete: vi.fn().mockResolvedValue(undefined),
    },
    sessions: {
      list: vi.fn().mockResolvedValue([]),
      tree: vi.fn().mockResolvedValue([]),
      read: vi.fn().mockResolvedValue(projection),
      log: vi.fn().mockResolvedValue([]),
    },
    turns: { running: vi.fn().mockResolvedValue(null), send: vi.fn() },
    workspace: {
      readFile: vi.fn().mockResolvedValue({ content: '', truncated: false }),
      history: vi.fn().mockResolvedValue([]),
    },
  })
}

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

/** **Every tab in the strip, clicked, in CI.** This is the coverage gap that
 *  let a tab bounce its own readers to another tab for a whole slice.
 *
 * The defect: "Holding session" wrote `select(null)` on the argument that
 * `null` lands back on that tab through `DEFAULT_MATERIAL`. The default moved
 * to `catalog` (#286), the arm did not move with it, and clicking the tab
 * navigated to Curriculum. Nothing caught it, and the reason was structural:
 * the jsdom suite asserted the strip and the panels, and the only file that
 * *clicked* a tab lived in the browser project, which CI does not run.
 *
 * Three things a click can be wrong about, and jsdom can judge all three: the
 * address it writes, which trigger ends up selected, and which panel is on
 * screen underneath. Nothing here is a measurement, so nothing here belongs in
 * the browser suite.
 *
 * Parametrised over the rendered strip rather than over a list written here.
 * A copy would be a second list to forget, and the tab this was written for is
 * exactly the one somebody would forget to add. The tabs are read off the DOM
 * for the same reason `visibleMaterialTabs` is filtered: which tabs a project
 * is offered is the render's decision, and this asserts about the ones it made.
 *
 * Reverted -- `onValueChange`'s `area` arm deleted so Curriculum writes
 * `#/p/<id>/area` -- the Curriculum case fails on the hash. */
it('selects the tab a reader clicks, and lands them on its panel', async () => {
  const user = userEvent.setup()
  window.location.hash = `#/p/${ATLAS}`
  renderApp(withWorkspace())

  // Awaited before the strip is read: the Workspace tab is conditional on a
  // query, so a strip read on the first paint is a strip missing a tab.
  await screen.findByRole('tab', { name: 'Workspace' })
  const labels = screen.getAllByRole('tab').map((tab) => tab.textContent)
  expect(labels).toContain('Workspace')
  expect(labels).not.toContain('Holding session')

  for (const label of labels) {
    await user.click(screen.getByRole('tab', { name: label }))

    // The address moved off the bare project href, which is what
    // `select(null)` failed to do -- and it is the assertion that separates
    // "the tab looks selected" from "the URL says so too". Curriculum is the
    // one tab whose facet is not its id, so the shape rather than the literal.
    expect(window.location.hash).not.toBe(`#/p/${ATLAS}`)
    expect(window.location.hash.startsWith(`#/p/${ATLAS}/`)).toBe(true)
    // Selected, and the only one. Radix leaves *every* trigger unselected when
    // its value names no trigger, which is the silent half of the same defect.
    const selected = screen.getAllByRole('tab').filter((tab) => tab.dataset.state === 'active')
    expect(selected.map((tab) => tab.textContent)).toEqual([label])
  }
})

/** The one selection on this page whose facet is not a tab id.
 *
 * `href` writes `#/p/<id>/session/<sid>[/at][?path]` for every scrub and every
 * file open in the Workspace, and `session` has no trigger in the strip -- it
 * had one until the holding-session tab was removed. So the mapping in
 * `materialTab` is the only thing keeping a scrub from selecting nothing at
 * all, and Radix's failure mode there is silent: a panel open below a strip
 * with no tab chosen.
 *
 * Reverted -- `materialTab`'s `session` arm removed -- this fails on the
 * selected tab, not on the panel. */
it('opens a session selection on the Workspace tab, which is the only tab it has', async () => {
  window.location.hash = `#/p/${ATLAS}/session/${TIP}`
  renderApp(withWorkspace())

  const workspace = await screen.findByRole('tab', { name: 'Workspace' })
  expect(workspace).toHaveAttribute('aria-selected', 'true')
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
  [`#/p/${ATLAS}/timeline`, 'project/timeline'],
  // An unrecognised facet parses as home rather than as a project route, so
  // the log cannot grow a view name nobody chose.
  [`#/p/${ATLAS}/wat`, 'home'],
  // The explorer files its own rows under its own name. Deliberate, and
  // argued at `viewNameOf`: a reader who sees `interactions` high in a view
  // count is seeing themselves, which is honest, where filtering it out would
  // leave the one view whose figures are known to be wrong unfalsifiable.
  ['#/i', 'interactions'],
  ['#/i?kind=ViewExited', 'interactions'],
])('names the view for %s', (hash, expected) => {
  expect(viewNameOf(parseRoute(hash))).toBe(expected)
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
  // It used to compare against the Holding session tab, which was first in the
  // strip and the previous default. That tab is gone -- a person does not pick
  // which session to read a project through -- so the pair is made with the
  // first tab that is actually offered, whichever it is. A single
  // `aria-selected="true"` proves nothing on its own: Radix selects nothing at
  // all when its value names no trigger, and one unselected peer is what tells
  // that state apart from a working default.
  expect(screen.queryByRole('tab', { name: 'Holding session' })).not.toBeInTheDocument()
  const others = screen.getAllByRole('tab').filter((tab) => tab !== curriculum)
  expect(others.length).toBeGreaterThan(0)
  for (const tab of others) expect(tab).toHaveAttribute('aria-selected', 'false')
})

/** A project nothing has ever been written in has no workspace, so it is
 *  offered no Workspace tab.
 *
 * **The condition under this changed with its data source and the test changed
 * with it.** It was "nothing is *holding* the project", which hid the tab for
 * every project between sessions -- all of which have files. The tab was right
 * to hide at the time, because the panel behind it read the holder and would
 * have been empty: 14 entries, 0.7s median, 100% bounce, which is what
 * arriving at an `EmptyState` and leaving looks like in aggregate. Widening the
 * gate without moving the data source would have reproduced exactly that.
 *
 * What is left behind the gate is a project with no reading head at all --
 * nothing written, nothing to show -- and the container's `project` read
 * answers no `readingHeadSessionId`, which is that state.
 *
 * The second assertion is what stops this passing vacuously: a strip that
 * failed to render at all would satisfy the `queryByRole` alone.
 *
 * Reverted -- `TabList` given `MATERIAL_TABS` again -- this fails on the
 * first line, because the trigger is rendered whatever the panel would say. */
it('offers no Workspace tab for a project nothing has been written in', async () => {
  window.location.hash = `#/p/${ATLAS}`
  renderApp()

  await screen.findByRole('tab', { name: 'Curriculum' })
  expect(screen.queryByRole('tab', { name: 'Workspace' })).not.toBeInTheDocument()
  expect(screen.getByRole('tab', { name: 'Documents' })).toBeInTheDocument()
})

/** **The tab is offered for a released project, and it is not empty.**
 *
 * This is the claim the slice is for, and both halves have to be here. The tab
 * appearing is what a widened gate would also achieve; the *file* is what says
 * the data source moved with it. A reader of this test a year from now should
 * be able to tell those two changes apart, and the only assertion that can is
 * the second one.
 *
 * The project is held by nobody -- `activeSessionId: null` -- so every reader
 * that resolves off the holder sees nothing here. `readingHeadSessionId` names
 * the tip session, and the file below folds out of it.
 *
 * Reverted -- `sessionId` back to `holdingSessionId` in `ProjectView` -- this
 * fails on the first line: the gate closes and the tab is not rendered. */
it('offers a Workspace with files for a project nobody is holding', async () => {
  const user = userEvent.setup()
  window.location.hash = `#/p/${ATLAS}`
  renderApp(withWorkspace())

  await user.click(await screen.findByRole('tab', { name: 'Workspace' }))

  const files = await screen.findByRole('listbox', { name: 'files' })
  expect(within(files).getByRole('option', { name: /notes\.md/ })).toBeInTheDocument()
  expect(screen.queryByText(/Nothing has been written here yet/)).not.toBeInTheDocument()
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
 * It ran against `finding` on a project whose course 409'd, until both went
 * with the workflow system. `file` is the only conditional tab now, so this
 * runs against the same project as the test above -- nothing holds it, the
 * Workspace tab is hidden there, and naming it in the route brings it back
 * selected.
 *
 * Reverted -- the `tab.id === openTab` line removed -- this fails on both
 * assertions. */
it('keeps a hidden tab that the route explicitly names, and selects it', async () => {
  window.location.hash = `#/p/${ATLAS}/file/notes.md`
  renderApp()

  const workspace = await screen.findByRole('tab', { name: 'Workspace' })
  expect(workspace).toHaveAttribute('aria-selected', 'true')
})

/** The header link, and then the page it reaches.
 *
 * Both halves in one test on purpose. A link with the right `href` that leads
 * to a route nothing renders is the defect the dialogue-page comment above
 * records in reverse -- there, a working page with no link; here, the link is
 * the easy half and the route switch is the half that can silently answer
 * `TreeView`, because that is what the switch does with every name it does not
 * know.
 *
 * Proved red by removing the `route.name === 'interactions'` arm from
 * `CurrentView`: the link is still found and still clicked, and the heading
 * never appears -- the landing page renders instead.
 */
it('reaches the interaction log from the header, beside the brand', async () => {
  renderApp()

  const banner = await screen.findByRole('banner')
  const link = within(banner).getByRole('link', { name: /^log$/i })
  expect(link).toHaveAttribute('href', '#/i')

  await userEvent.click(link)

  expect(await screen.findByRole('heading', { name: /interaction log/i })).toBeInTheDocument()
})
