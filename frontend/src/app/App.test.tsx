import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'

import { App } from './App.tsx'

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
      outputs: [],
      gateDecisions: [],
      reviewerRole: null,
      findingsReport: null,
    },
  ],
  findings: [],
  unimplementedChecks: [],
}

const containerWith = (over: Record<string, unknown> = {}) =>
  ({
    now: () => NOW,
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
  await user.click(screen.getByRole('button', { name: 'Delete' }))

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

it('sends the graph facets to the research view and the rest to the course', async () => {
  // The dispatch is `App.tsx`'s alone and temporary -- it exists only until the
  // two views merge -- so nothing else in the repository would notice it being
  // wrong. Two assertions rather than one: a branch that sent *everything* to
  // one view would satisfy either on its own.
  window.location.hash = `#/p/${ATLAS}/entity/e1`
  const { unmount } = renderApp()
  expect(await screen.findByRole('heading', { name: 'Research' })).toBeInTheDocument()
  unmount()

  window.location.hash = `#/p/${ATLAS}/stage/step1.framing`
  renderApp()
  expect(await screen.findByRole('heading', { name: 'Hybrid' })).toBeInTheDocument()
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
