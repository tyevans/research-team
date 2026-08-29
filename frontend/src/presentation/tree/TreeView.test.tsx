import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { ProjectListing, ProjectSummary } from '@domain/project/project.ts'
import type { SessionSummary } from '@domain/session/session.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { TreeView } from './TreeView.tsx'

/** The index, as a page rather than as measurements.
 *
 * Roles, text, routing and the two writes. Anything whose answer is a computed
 * style or a resolved width is in `project-board.browser.test.tsx`, where a
 * browser is doing the laying out — jsdom applies no stylesheet, so a bar's
 * width and a marker's colour are both unaskable here.
 *
 * **What this file lost with the page it covers.** The old version had
 * twenty-two cases, and about half were about sessions: which one a row
 * previewed, folding the fork forest, the `held` chip, searching a session's
 * first message. None of that is on the index now. What is left is the part
 * that was always about *projects*, plus the pipeline the page is built
 * around.
 */

const ATLAS = ProjectId('11111111-1111-1111-1111-111111111111')
const SANDBOX = ProjectId('22222222-2222-2222-2222-222222222222')
const HOLDER = SessionId('3f2a0000-0000-0000-0000-000000000000')

const NOW = Date.parse('2026-08-09T12:00:00Z')

const EMPTY: ProjectSummary = {
  topics: 0,
  topicsOpen: 0,
  sources: 0,
  extracted: 0,
  courses: 0,
  sessions: 0,
  lastActivity: null,
}

const project = (
  id: ProjectId,
  name: string,
  summary: Partial<ProjectSummary> = {},
  over: Partial<ProjectListing> = {},
): ProjectListing => ({
  id,
  name,
  activeSessionId: null,
  tipAtEvent: 0,
  summary: { ...EMPTY, lastActivity: '2026-08-09T09:00:00Z', ...summary },
  ...over,
})

const session = (id: string, over: Partial<SessionSummary> = {}): SessionSummary => ({
  id: SessionId(id),
  projectId: ATLAS,
  startedAt: '2026-08-09T09:00:00Z',
  turns: 0,
  files: 0,
  firstMessage: null,
  forkedFrom: null,
  forkedAt: null,
  failedTurns: 0,
  ...over,
})

/** A container of fakes, with every port this page touches answered.
 *
 * Liveness and health answer "nothing happening, nothing wrong" by default:
 * they are the two reads that render *extra* chrome, so leaving them out of a
 * test that is not about them keeps the assertions on the rows.
 */
const containerWith = ({
  projects = [] as readonly ProjectListing[],
  sessions = [] as readonly SessionSummary[],
  /** The listing spy itself, for the one test that counts its calls.
   *
   * A parameter rather than something smuggled through `...rest`, which is what
   * the first draft did: `rest` overwrites the whole `projects` object, so the
   * container lost `join` and `delete` and `list` answered the object it had
   * been handed instead of an array. It failed as a render timeout naming
   * nothing about any of that. */
  list,
  // The two write ports are taken as arguments rather than read back off the
  // built container. `@typescript-eslint/unbound-method` rejects
  // `expect(container.projects.join)` — a method reference plucked off an
  // object — and it is right to: the assertion wants the spy, and the spy is
  // what a caller can hold.
  join = vi.fn(),
  del = vi.fn().mockResolvedValue(undefined),
  ...rest
}: {
  projects?: readonly ProjectListing[]
  sessions?: readonly SessionSummary[]
  list?: ReturnType<typeof vi.fn>
  join?: ReturnType<typeof vi.fn>
  del?: ReturnType<typeof vi.fn>
  [key: string]: unknown
}) =>
  ({
    now: () => NOW,
    sessions: {
      list: vi.fn().mockResolvedValue(sessions),
      tree: vi.fn().mockResolvedValue(sessions.map((row) => ({ ...row, children: [] }))),
    },
    projects: {
      list: list ?? vi.fn().mockResolvedValue(projects),
      create: vi.fn(),
      join,
      delete: del,
    },
    workers: { everywhere: vi.fn().mockResolvedValue([]) },
    health: {
      summaries: vi.fn().mockResolvedValue({ healthy: true, following: true, failedEvents: 0 }),
      rebuildSummaries: vi.fn(),
    },
    ...rest,
  }) as unknown as AppContainer

const renderPage = (ui: ReactElement, container: AppContainer) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  // An `OverlayHost`, because this page opens a `Confirm` and a `Menu`, both of
  // which are `Overlay`s and render nothing without one. In the application
  // this comes from `Shell`.
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <OverlayHost>{children}</OverlayHost>
      </ContainerProvider>
    </QueryClientProvider>
  )
  return render(ui, { wrapper })
}

/** The row an assertion is about, found by the project's name.
 *
 * `closest` off the link rather than an nth-child, so a test says which
 * project it means rather than which position it happened to be in — the
 * board is sortable, and a positional selector would break on a sort change
 * for reasons unrelated to what it was checking.
 */
const rowFor = (name: string) =>
  within(screen.getByRole('link', { name }).closest('[data-board-row]') as HTMLElement)

beforeEach(() => {
  window.location.hash = ''
})

it('answers an empty database with one page and one action, not an empty board', async () => {
  renderPage(<TreeView />, containerWith({}))

  // The only wait in this file that needs two queries to settle before the
  // element exists at all: the first-run page renders once the projects list
  // *and* the session list have both answered empty, since showing it while
  // either is in flight would tell a returning reader their work is gone.
  expect(
    await screen.findByRole('button', { name: 'Create project' }, { timeout: 5000 }),
  ).toBeInTheDocument()
  expect(screen.getByText(/outlives one conversation/i)).toBeInTheDocument()
  expect(screen.getByText(/uv run main\.py/)).toBeInTheDocument()
  // No search and no sort: there is nothing to search or order.
  expect(screen.queryByLabelText(/find a project/i)).not.toBeInTheDocument()
})

it('teaches the four stages on the first-run page, where somebody is reading', async () => {
  // The vocabulary every row uses. A first-time reader cannot infer from three
  // unlabelled bars that sources arrive by investigating topics, and this is
  // the one screen where explaining it costs a returning reader nothing —
  // they never see it again.
  renderPage(<TreeView />, containerWith({}))
  await screen.findByRole('button', { name: 'Create project' }, { timeout: 5000 })

  const stages = screen.getByRole('list')

  expect(within(stages).getByText('Topics')).toBeInTheDocument()
  expect(within(stages).getByText('Sources')).toBeInTheDocument()
  expect(within(stages).getByText('Graph')).toBeInTheDocument()
  expect(within(stages).getByText('Courses')).toBeInTheDocument()
})

it('draws each project’s pipeline, so two projects are told apart by their state', async () => {
  // The whole point of the redesign. The previous index gave every project a
  // session count and a file count, so six rows differed only in a name; this
  // asserts that the four stage counts reach the row, per project.
  renderPage(
    <TreeView />,
    containerWith({
      projects: [
        project(ATLAS, 'atlas', { topics: 14, sources: 11, extracted: 11, courses: 2 }),
        project(SANDBOX, 'sandbox', { topics: 3, sources: 0, extracted: 0, courses: 0 }),
      ],
      sessions: [session('a')],
    }),
  )
  expect(await screen.findByRole('link', { name: 'atlas' })).toBeInTheDocument()

  const atlas = rowFor('atlas')
  expect(atlas.getByLabelText('14 topics')).toBeInTheDocument()
  expect(atlas.getByLabelText('11 sources')).toBeInTheDocument()
  expect(atlas.getByLabelText('2 courses')).toBeInTheDocument()

  const sandbox = rowFor('sandbox')
  expect(sandbox.getByLabelText('3 topics')).toBeInTheDocument()
  expect(sandbox.getByLabelText('0 sources')).toBeInTheDocument()
})

it('says how much ingested material has not been extracted', async () => {
  // The one thing on this page a reader can act on immediately, and a state the
  // previous index could not express at all — measured on the real database,
  // two of six projects were in it.
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas', { sources: 6, extracted: 3 })],
      sessions: [session('a')],
    }),
  )
  expect(await screen.findByRole('link', { name: 'atlas' })).toBeInTheDocument()

  expect(rowFor('atlas').getByText('3 not extracted')).toBeInTheDocument()
  // The accessible name carries it too: the bar is `role="img"`, so the note is
  // the whole of what a reader who cannot see it gets.
  expect(rowFor('atlas').getByLabelText('6 sources, 3 not extracted')).toBeInTheDocument()
})

it('says nothing about extraction when there is nothing outstanding', async () => {
  // The negative half, and the one that would have caught the inverted-tone
  // defect at the level of words rather than colour: a complete project must
  // not be marked.
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas', { sources: 6, extracted: 6 })],
      sessions: [session('a')],
    }),
  )
  expect(await screen.findByRole('link', { name: 'atlas' })).toBeInTheDocument()

  expect(rowFor('atlas').queryByText(/not extracted/)).not.toBeInTheDocument()
})

it('marks queued topics as a backlog rather than as progress', async () => {
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas', { topics: 8, topicsOpen: 8 })],
      sessions: [session('a')],
    }),
  )
  expect(await screen.findByRole('link', { name: 'atlas' })).toBeInTheDocument()

  expect(rowFor('atlas').getByText('8 queued')).toBeInTheDocument()
})

it('shows when a project was last touched, and says so plainly when never', async () => {
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas', { lastActivity: null })],
      sessions: [session('a')],
    }),
  )
  expect(await screen.findByRole('link', { name: 'atlas' })).toBeInTheDocument()

  expect(rowFor('atlas').getByText('never opened')).toBeInTheDocument()
})

it('reaches the project page from the row’s name, as a link', async () => {
  // A link rather than a click handler, so ⌘-click and "copy link" work. The
  // name used to be an inert `<span>` while the way to a project page was a
  // small secondary button four controls along.
  renderPage(
    <TreeView />,
    containerWith({ projects: [project(ATLAS, 'atlas')], sessions: [session('a')] }),
  )

  expect(await screen.findByRole('link', { name: 'atlas' })).toHaveAttribute('href', `#/p/${ATLAS}`)
})

it('reaches the ask page, which no tab on the project view can reach', async () => {
  // `App.tsx` intercepts the `ask` facet above `ProjectView`, so this menu item
  // is the difference between a page a reader can find and one only a typed URL
  // reaches.
  renderPage(
    <TreeView />,
    containerWith({ projects: [project(ATLAS, 'atlas')], sessions: [session('a')] }),
  )
  await screen.findByRole('link', { name: 'atlas' })

  await userEvent.click(screen.getByRole('button', { name: 'More actions for atlas' }))
  await userEvent.click(await screen.findByRole('menuitem', { name: 'Ask' }))

  expect(window.location.hash).toBe(`#/p/${ATLAS}/ask`)
})

it('continues a held project into the session already open, without a dialog', async () => {
  const join = vi.fn()
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas', {}, { activeSessionId: HOLDER })],
      sessions: [session('a')],
      join,
    }),
  )
  await screen.findByRole('link', { name: 'atlas' })

  await userEvent.click(screen.getByRole('button', { name: 'Continue' }))

  expect(window.location.hash).toBe(`#/s/${HOLDER}`)
  expect(join).not.toHaveBeenCalled()
})

it('continues a free project by starting a session in it', async () => {
  // The other arm of the same verb. Which one happened is never told to the
  // reader, because the answer is the same either way: they are looking at the
  // project's live conversation.
  const started = SessionId('44444444-4444-4444-4444-444444444444')
  const join = vi.fn().mockResolvedValue({ sessionId: started, warning: null })
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas')],
      sessions: [session('a')],
      join,
    }),
  )
  await screen.findByRole('link', { name: 'atlas' })

  await userEvent.click(screen.getByRole('button', { name: 'Continue' }))

  expect(join).toHaveBeenCalledWith(ATLAS, false)
  await vi.waitFor(() => expect(window.location.hash).toBe(`#/s/${started}`))
})

it('keeps the delete confirmation’s wording, in the console’s own dialog', async () => {
  // "Delete" does something a reader will assume is worse than it is. This is
  // the sentence that says so, kept word for word across the redesign.
  renderPage(
    <TreeView />,
    containerWith({ projects: [project(ATLAS, 'atlas')], sessions: [session('a')] }),
  )
  await screen.findByRole('link', { name: 'atlas' })

  await userEvent.click(screen.getByRole('button', { name: 'More actions for atlas' }))
  await userEvent.click(await screen.findByRole('menuitem', { name: 'Delete' }))

  expect(await screen.findByText(/Delete project "atlas"\?/)).toBeInTheDocument()
  expect(screen.getByText(/they just cannot rejoin/i)).toBeInTheDocument()
  expect(screen.getByText(/knowledge graph's contents are left in place/i)).toBeInTheDocument()
})

it('still ends the holding session when a held project is deleted', async () => {
  // `isHeld` is the last load-bearing read of the holder on this page and
  // nothing draws it, so it is the argument that would rot silently: a `false`
  // here fails against exactly the projects a person is most likely to delete.
  const del = vi.fn().mockResolvedValue(undefined)
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas', {}, { activeSessionId: HOLDER })],
      sessions: [session('a')],
      del,
    }),
  )
  await screen.findByRole('link', { name: 'atlas' })

  await userEvent.click(screen.getByRole('button', { name: 'More actions for atlas' }))
  await userEvent.click(await screen.findByRole('menuitem', { name: 'Delete' }))
  expect(await screen.findByText(/A session is still holding it/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Delete project' }))

  expect(del).toHaveBeenCalledWith(ATLAS, true)
})

it('does not force the flag for a project nothing is holding', async () => {
  const del = vi.fn().mockResolvedValue(undefined)
  renderPage(
    <TreeView />,
    containerWith({ projects: [project(ATLAS, 'atlas')], sessions: [session('a')], del }),
  )
  await screen.findByRole('link', { name: 'atlas' })

  await userEvent.click(screen.getByRole('button', { name: 'More actions for atlas' }))
  await userEvent.click(await screen.findByRole('menuitem', { name: 'Delete' }))
  expect(screen.queryByText(/A session is still holding it/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Delete project' }))

  expect(del).toHaveBeenCalledWith(ATLAS, false)
})

it('marks a project something is running in', async () => {
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas'), project(SANDBOX, 'sandbox')],
      sessions: [session('a')],
      workers: {
        everywhere: vi
          .fn()
          .mockResolvedValue([
            { projectId: ATLAS, workers: [{ kind: 'run', detail: '', startedAt: null }] },
          ]),
      },
    }),
  )
  await screen.findByRole('link', { name: 'atlas' })

  expect(await rowFor('atlas').findByText(/run running/)).toBeInTheDocument()
  // And nothing on the project with no roster entry: `everywhere()` omits a
  // project with nothing running rather than answering an empty roster, so
  // "not found" is "nothing is happening here".
  expect(rowFor('sandbox').queryByText(/running/)).not.toBeInTheDocument()
})

it('prefers a run over a turn when both are live in one project', async () => {
  // `everywhere()` says nothing about the order within a roster, so taking
  // `workers[0]` would make the label depend on whatever order the server
  // happened to fold in. This fails if the precedence becomes positional.
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas')],
      sessions: [session('a')],
      workers: {
        everywhere: vi.fn().mockResolvedValue([
          {
            projectId: ATLAS,
            workers: [
              { kind: 'turn', detail: '', startedAt: null },
              { kind: 'run', detail: '', startedAt: null },
            ],
          },
        ]),
      },
    }),
  )
  await screen.findByRole('link', { name: 'atlas' })

  expect(await rowFor('atlas').findByText(/run running/)).toBeInTheDocument()
})

it('says how long a turn has been running', async () => {
  // Moved here from `ProjectActivity.test.tsx`, which covered the hook this
  // page no longer has. It is the assertion that caught the suffix being
  // dropped when that hook's body moved into `activityOf`: the chip still read
  // "turn running", which is plausible enough that nothing looked wrong.
  //
  // A *turn* rather than a run, deliberately — the server sends
  // `startedAt: null` for a run worker, so a run has no suffix to lose and
  // could never have failed this.
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas')],
      sessions: [session('a')],
      workers: {
        everywhere: vi.fn().mockResolvedValue([
          {
            projectId: ATLAS,
            workers: [
              { kind: 'turn', detail: '', startedAt: new Date(NOW - 240_000).toISOString() },
            ],
          },
        ]),
      },
    }),
  )
  await screen.findByRole('link', { name: 'atlas' })

  expect(await rowFor('atlas').findByText(/turn running · /)).toBeInTheDocument()
})

it('asks for the roster once for the whole board, however many rows are drawn', async () => {
  // The claim that justifies hoisting the read out of the row. Three rows, one
  // request — React Query dedupes by key, so this fails if a future edit puts a
  // `useQuery` back inside `ProjectBoardRow`.
  const everywhere = vi.fn().mockResolvedValue([])
  renderPage(
    <TreeView />,
    containerWith({
      projects: [
        project(ATLAS, 'atlas'),
        project(SANDBOX, 'sandbox'),
        project(ProjectId('33333333-3333-3333-3333-333333333333'), 'third'),
      ],
      sessions: [session('a')],
      workers: { everywhere },
    }),
  )
  await screen.findByRole('link', { name: 'third' })

  expect(everywhere).toHaveBeenCalledTimes(1)
})

it('does not degrade a row when its liveness read fails', async () => {
  // The row is still a working link to the project, and an error where a chip
  // would go says nothing a reader can act on.
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas', { sources: 4, extracted: 4 })],
      sessions: [session('a')],
      workers: { everywhere: vi.fn().mockRejectedValue(new Error('roster is down')) },
    }),
  )

  expect(await screen.findByRole('link', { name: 'atlas' })).toBeInTheDocument()
  expect(rowFor('atlas').getByLabelText('4 sources')).toBeInTheDocument()
  expect(screen.queryByText(/roster is down/)).not.toBeInTheDocument()
})

it('filters projects by name', async () => {
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas'), project(SANDBOX, 'sandbox')],
      sessions: [session('a')],
    }),
  )
  await screen.findByRole('link', { name: 'atlas' })

  await userEvent.type(screen.getByLabelText(/find a project/i), 'sand')

  expect(screen.queryByRole('link', { name: 'atlas' })).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'sandbox' })).toBeInTheDocument()
})

it('says which search found nothing rather than showing an empty board', async () => {
  renderPage(
    <TreeView />,
    containerWith({ projects: [project(ATLAS, 'atlas')], sessions: [session('a')] }),
  )
  await screen.findByRole('link', { name: 'atlas' })

  await userEvent.type(screen.getByLabelText(/find a project/i), 'fizzbuzz')

  expect(screen.getByText(/No project is called “fizzbuzz”/)).toBeInTheDocument()
})

it('clears the search and gives focus back on Escape', async () => {
  // `type="search"` gives you this in WebKit and in no other engine, and even
  // there only as a clear, leaving focus in a box the reader has finished with.
  renderPage(
    <TreeView />,
    containerWith({ projects: [project(ATLAS, 'atlas')], sessions: [session('a')] }),
  )
  await screen.findByRole('link', { name: 'atlas' })
  const box = screen.getByLabelText(/find a project/i)

  await userEvent.type(box, 'fizz')
  await userEvent.type(box, '{Escape}')

  expect(box).toHaveValue('')
  expect(box).not.toHaveFocus()
})

it('reorders the board without refetching', async () => {
  // A radio group rather than buttons with `aria-pressed`: exactly one ordering
  // is chosen at a time. The assertion is on the *order of the names*, which is
  // the only thing a sort can be wrong about.
  const list = vi
    .fn()
    .mockResolvedValue([
      project(ATLAS, 'zebra', { lastActivity: '2026-08-09T11:00:00Z' }),
      project(SANDBOX, 'aardvark', { lastActivity: '2026-08-09T09:00:00Z' }),
    ])
  renderPage(<TreeView />, containerWith({ sessions: [session('a')], list }))
  await screen.findByRole('link', { name: 'zebra' })

  const names = () => screen.getAllByRole('link').map((link) => link.textContent)
  expect(names()).toEqual(['zebra', 'aardvark'])

  await userEvent.click(screen.getByRole('radio', { name: 'Name' }))

  expect(names()).toEqual(['aardvark', 'zebra'])
  // One fetch, not two: sorting is a fold over what is already here.
  expect(list).toHaveBeenCalledTimes(1)
})

it('says the projections may be lying, in the page rather than only in the topbar', async () => {
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas')],
      sessions: [session('a')],
      health: {
        // `following: true`: a projection that has *stopped* following offers no
        // button at all, because a browser cannot restart one. The drifted-but-
        // following case is the one with a rebuild in it.
        summaries: vi.fn().mockResolvedValue({ healthy: false, following: true, failedEvents: 3 }),
        rebuildSummaries: vi.fn(),
      },
    }),
  )

  expect(await screen.findByRole('button', { name: /rebuild/i })).toBeInTheDocument()
})

it('does not re-explain itself to a returning reader', async () => {
  // The two paragraphs and the stage list are on the first-run page, where
  // somebody is reading them for the first time. A returning reader has been
  // here two hundred times.
  renderPage(
    <TreeView />,
    containerWith({ projects: [project(ATLAS, 'atlas')], sessions: [session('a')] }),
  )
  await screen.findByRole('link', { name: 'atlas' })

  expect(screen.queryByText(/outlives one conversation/i)).not.toBeInTheDocument()
  expect(screen.queryByText(/what investigating a topic fetches/i)).not.toBeInTheDocument()
})
