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
import { ProjectId, SessionId, SourceId } from '@domain/shared/identifier.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'
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
      whole: vi.fn().mockResolvedValue({ entities: [], relations: [], truncated: false }),
      neighborhood: vi.fn().mockResolvedValue({ entities: [], relations: [] }),
      search: vi.fn().mockResolvedValue({ entities: [], types: [] }),
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

it('hands the selected entity to the graph, not just the view', async () => {
  // The id has to survive the facet, not only the route: a dispatch that
  // reached `ResearchView` with `entity` hard-null would satisfy the test
  // above and draw the wrong graph.
  const neighborhood = vi.fn().mockResolvedValue({ entities: [], relations: [] })
  window.location.hash = `#/p/${ATLAS}/entity/e1`
  renderApp(
    containerWith({
      graphs: {
        whole: vi.fn().mockResolvedValue({ entities: [], relations: [], truncated: false }),
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
  // `viewNameOf` now imports rather than repeats.
  [`#/p/${ATLAS}`, 'project/session'],
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
