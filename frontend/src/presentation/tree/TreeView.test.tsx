import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Project } from '@domain/project/project.ts'
import type { SessionSummary } from '@domain/session/session.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { TreeView } from './TreeView.tsx'

const ATLAS = ProjectId('11111111-1111-1111-1111-111111111111')
const SANDBOX = ProjectId('22222222-2222-2222-2222-222222222222')
const HOLDER = SessionId('3f2a0000-0000-0000-0000-000000000000')

const NOW = Date.parse('2026-08-09T12:00:00Z')

const project = (id: ProjectId, name: string, over: Partial<Project> = {}): Project => ({
  id,
  name,
  activeSessionId: null,
  tipAtEvent: 0,
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
 * test that is not about them keeps the assertions about the rows.
 */
const containerWith = ({
  projects = [] as readonly Project[],
  sessions = [] as readonly SessionSummary[],
  tree,
  ...rest
}: {
  projects?: readonly Project[]
  sessions?: readonly SessionSummary[]
  tree?: readonly SessionSummary[]
  [key: string]: unknown
}) =>
  ({
    now: () => NOW,
    sessions: {
      list: vi.fn().mockResolvedValue(sessions),
      // The fork tree is the flat rows with no children unless a test says
      // otherwise, which is what the server answers for unforked sessions.
      tree: vi.fn().mockResolvedValue((tree ?? sessions).map((row) => ({ ...row, children: [] }))),
    },
    projects: {
      list: vi.fn().mockResolvedValue(projects),
      create: vi.fn(),
      join: vi.fn(),
      delete: vi.fn().mockResolvedValue(undefined),
    },
    research: { current: vi.fn().mockResolvedValue(null) },
    // `everywhere` rather than `on`: the row's liveness chip reads the global
    // roster now. Empty means no chip, which is what every test in this file
    // wants — the chip's own behaviour is `ProjectActivity.test.tsx`'s subject.
    workers: { everywhere: vi.fn().mockResolvedValue([]) },
    health: {
      summaries: vi.fn().mockResolvedValue({ healthy: true, following: true, failedEvents: 0 }),
      rebuildSummaries: vi.fn(),
    },
    ...rest,
  }) as unknown as AppContainer

const renderPage = (ui: ReactElement, container: AppContainer) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  // An `OverlayHost`, because this page opens a `Drawer`/`Confirm`, both of
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

beforeEach(() => {
  window.location.hash = ''
})

it('answers an empty database with one page and one action, not two empty boxes', async () => {
  // Both lists empty used to render an empty state for sessions suggesting the
  // CLI and a second one for projects saying something different, under two
  // headings. The whole page is the answer instead, and the action it offers
  // is creating a project, which is now the only way to start work at all.
  renderPage(<TreeView />, containerWith({}))

  // The only wait in this file that needs two queries to settle before the
  // element exists at all: the first-run page renders once the projects list
  // *and* the session list have both answered empty, since showing it while
  // either is in flight would tell a returning reader their work is gone.
  // Two settles plus the re-render is more than the default one second under
  // a loaded full-suite run, which is what made this flake there and pass in
  // isolation.
  expect(
    await screen.findByRole('button', { name: 'Create project' }, { timeout: 5000 }),
  ).toBeInTheDocument()
  expect(screen.getByText(/outlives one conversation/i)).toBeInTheDocument()
  // The CLI stays; the bare session does not. Every session belongs to a
  // project, so there is no prompt to try without one.
  expect(screen.queryByRole('button', { name: /bare session/i })).not.toBeInTheDocument()
  expect(screen.getByText(/uv run main\.py/)).toBeInTheDocument()
  // No search and no section headings: there is nothing to search or head.
  expect(screen.queryByLabelText(/search projects/i)).not.toBeInTheDocument()
})

it('leads with projects and puts their sessions inside them', async () => {
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas')],
      sessions: [
        session('a', { projectId: ATLAS, firstMessage: 'How does spacing affect retention?' }),
        session('b', { projectId: SANDBOX, firstMessage: 'a session of another project' }),
      ],
    }),
  )

  // `.ent-project-card`, not `.project`: the landing page draws a project with
  // `ProjectCard` now. The selector moved with the markup; nothing about what
  // this test asserts did.
  const row = (await screen.findByText('atlas')).closest('.ent-project-card')!
  expect(within(row as HTMLElement).getByText('1 session')).toBeInTheDocument()
  expect(
    within(row as HTMLElement).getByText(/How does spacing affect retention/),
  ).toBeInTheDocument()

  // A session of a project this listing does not include has nowhere on this
  // page to appear, and must not be counted into or drawn inside another.
  expect(screen.queryByText(/a session of another project/)).not.toBeInTheDocument()
})

it('reaches all four of a project’s destinations from its row', async () => {
  const container = containerWith({
    projects: [project(ATLAS, 'atlas', { activeSessionId: HOLDER })],
    sessions: [session('a', { projectId: ATLAS })],
  })
  const user = userEvent.setup()
  renderPage(<TreeView />, container)

  // The holding session.
  await user.click(await screen.findByRole('button', { name: /Resume/ }))
  expect(window.location.hash).toBe(`#/s/${HOLDER}`)

  // The project page and the ask page: two buttons for two pages, where
  // "Course" and "Research" were two buttons for one. There is no course page
  // and no research page, so the second destination asserted here is the one
  // route the project view does *not* contain -- `App.tsx` intercepts `ask`
  // above `ProjectView` and renders a page of its own.
  await user.click(screen.getByRole('button', { name: 'Project' }))
  expect(window.location.hash).toBe(`#/p/${ATLAS}`)

  await user.click(screen.getByRole('button', { name: 'Ask' }))
  expect(window.location.hash).toBe(`#/p/${ATLAS}/ask`)

  // A new session *in it*, which ends the holder and so asks first. Scoped to
  // the row: the action bar's quiet "New session" is the bare-session one, and
  // the two are deliberately different things.
  const row = screen.getByText('atlas').closest('.ent-project-card')!
  await user.click(within(row as HTMLElement).getByRole('button', { name: 'New session' }))
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByText(/Its files carry over to the new session/)).toBeInTheDocument()
})

/** Every project has a project page, and this is the assertion that replaced
 *  its opposite twice over.
 *
 * It was first "disables Course with the server's own reason rather than
 * relabelling it" -- right about the reason and right about `aria-disabled`
 * over `disabled`, and both stopped mattering when the destination became the
 * project view rather than a course page. It then read "offers the project page
 * for a project that chose no workflow", which was a claim about a state that
 * no longer exists: there are no presets to choose or decline. What it still
 * guards is the button being unconditional, which is why it is kept rather than
 * deleted with the concept in its old name.
 */
it('offers the project page for every project', async () => {
  const user = userEvent.setup()
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(SANDBOX, 'sandbox')],
      sessions: [session('a', { projectId: SANDBOX })],
    }),
  )

  const toProject = await screen.findByRole('button', { name: 'Project' })
  expect(toProject).not.toHaveAttribute('aria-disabled')

  await user.click(toProject)
  expect(window.location.hash).toBe(`#/p/${SANDBOX}`)
})

/** The gap that let two buttons point at one page for a whole increment:
 *  nothing asserted that a route was *reachable*.
 *
 * Every other test of a destination renders the destination. That cannot
 * notice a missing door — the ask page has routed and worked throughout, and
 * for one increment the picker offered no way to it at all. So this asserts an
 * inbound affordance from the landing page and nothing about what it lands on.
 * It is the landing-page half of the same check `App.test.tsx` makes for the
 * project page's link to ask.
 *
 * **Not proved red** — see the note above; no test was run locally.
 */
it('offers a way into both project pages from the picker', async () => {
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas')],
      sessions: [session('a', { projectId: ATLAS })],
    }),
  )

  expect(await screen.findByRole('button', { name: 'Project' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Ask' })).toBeInTheDocument()

  // The names that used to be here are two addresses of one page. If either
  // comes back, the picker is describing a console that no longer exists.
  expect(screen.queryByRole('button', { name: 'Course' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Research' })).toBeNull()
})

it('falls back to the session list when the tree projection has drifted empty', async () => {
  // The fallback this page has always had: `/api/tree` answering nothing while
  // `/api/sessions` plainly has rows is a drifted projection, and using the
  // flat list is a truthful degradation where "no sessions" would be a lie.
  //
  // It is read through a project now rather than through a loose-session list,
  // which is the only place sessions appear -- so a drifted tree shows as a
  // project reporting no sessions and naming none, which is exactly the lie
  // the fallback exists to prevent.
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas')],
      sessions: [session('a', { projectId: ATLAS, firstMessage: 'still here' })],
      tree: [],
    }),
  )

  expect(await screen.findByText('still here')).toBeInTheDocument()
  expect(screen.getByText('1 session')).toBeInTheDocument()
})

/** **This used to assert `run · round 3`**, fed by a `research.current` fake
 *  that answered `progress: { status: 'running', rounds: 3 }`.
 *
 * The chip reads the global roster now, which carries no round count, so the
 * label is `run running` — a deliberate degradation recorded in
 * `ProjectActivity.tsx` and filed in `BACKLOG.md`. Rewritten rather than
 * deleted: this is the only assertion that the chip reaches the *card*, which
 * is a different claim from `ProjectActivity.test.tsx`'s about the hook, and a
 * slot wired to nothing would pass every test in that file.
 */
it('marks a project something is running in', async () => {
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas')],
      sessions: [session('a', { projectId: ATLAS })],
      workers: {
        everywhere: vi.fn().mockResolvedValue([
          {
            projectId: ATLAS,
            workers: [
              {
                kind: 'run',
                ref: 'r1',
                detail: 'autonomous run',
                sessionId: SessionId('a'),
                parent: null,
                startedAt: null,
              },
            ],
            idleSessionIds: [],
          },
        ]),
      },
    }),
  )

  expect(await screen.findByText(/run running/)).toBeInTheDocument()
})

it('does not degrade a row when its liveness read fails', async () => {
  // A row with no marker is still a working link to every page it offers. An
  // error where a chip would go says nothing anybody can act on.
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas')],
      sessions: [session('a', { projectId: ATLAS })],
      research: { current: vi.fn().mockRejectedValue(new Error('research is not wired up')) },
      workers: { on: vi.fn().mockRejectedValue(new Error('no roster')) },
    }),
  )

  expect(await screen.findByText('atlas')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Project' })).toBeEnabled()
  expect(screen.queryByText(/not wired up/)).not.toBeInTheDocument()
})

it('filters projects and their sessions by what was typed', async () => {
  const user = userEvent.setup()
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas'), project(SANDBOX, 'sandbox')],
      sessions: [
        session('a', { projectId: ATLAS, firstMessage: 'spaced repetition' }),
        session('b', { projectId: SANDBOX, firstMessage: 'something else' }),
      ],
    }),
  )

  await screen.findByText('atlas')
  await user.type(screen.getByLabelText(/search projects/i), 'spaced')

  expect(screen.getByText('atlas')).toBeInTheDocument()
  expect(screen.queryByText('sandbox')).not.toBeInTheDocument()
})

it('keeps the delete confirmation’s wording, in the console’s own dialog', async () => {
  const user = userEvent.setup()
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas', { activeSessionId: HOLDER })],
      sessions: [session('a', { projectId: ATLAS })],
    }),
  )

  await user.click(await screen.findByRole('button', { name: /More actions for atlas/ }))
  // `menuitem`, not `button`. The row menu was a `Disclosure` full of
  // `<button>`s until it became a `Menu`; the role change is the conversion's
  // whole point -- a disclosure has no arrow-key movement, no Escape and no
  // focus return -- so this query changing is the test recording it rather
  // than a query being loosened to keep a test green.
  await user.click(screen.getByRole('menuitem', { name: 'Delete' }))

  const dialog = await screen.findByRole('dialog', { name: /Delete/ })
  expect(dialog).toHaveAttribute('aria-modal', 'true')
  expect(
    within(dialog).getByText(/is still holding it and will be ended first/),
  ).toBeInTheDocument()
  expect(within(dialog).getByText(/cannot rejoin/)).toBeInTheDocument()
  expect(
    within(dialog).getByText(/knowledge graph's contents are left in place/),
  ).toBeInTheDocument()
})

it('says the session list may be lying, in the page rather than only in the topbar', async () => {
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas')],
      sessions: [session('a', { projectId: ATLAS })],
      health: {
        summaries: vi.fn().mockResolvedValue({ healthy: false, following: true, failedEvents: 4 }),
        rebuildSummaries: vi.fn(),
      },
    }),
  )

  expect(await screen.findByText(/4 events did not apply/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Rebuild the list/ })).toBeInTheDocument()
})

it('shows a project’s current session and keeps the rest folded away', async () => {
  // Sessions accumulate far faster than projects, so a row that listed all of
  // them buried every other project. The row shows the one line anybody was
  // reading -- the holder -- and the rest are one click away.
  const user = userEvent.setup()
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas', { activeSessionId: HOLDER })],
      sessions: [
        session(HOLDER, {
          projectId: ATLAS,
          firstMessage: 'the one still open',
          startedAt: '2026-08-01T00:00:00Z',
        }),
        session('older', {
          projectId: ATLAS,
          firstMessage: 'an older one',
          startedAt: '2026-07-01T00:00:00Z',
        }),
      ],
    }),
  )

  expect(await screen.findByText('the one still open')).toBeInTheDocument()
  expect(screen.queryByText('an older one')).not.toBeInTheDocument()

  // The fold is a control the view supplies and a region the card draws, which
  // is a seam `Disclosure` did not have -- it rendered both and wired them
  // together itself. So the wiring is asserted here rather than assumed: the
  // toggle's `aria-controls` has to resolve to a real element *while the fold
  // is shut*, which is when a reader most needs to be told what the button
  // opens. Both attributes are read off the same node deliberately; split
  // across two elements this reads correct in the DOM and announces a button
  // that expands nothing.
  //
  // Red before `ProjectCard` gave the region an id: with no `aria-controls`
  // the attribute is null, `getElementById` is handed null and answers null.
  const toggle = screen.getByRole('button', { name: /all 2 sessions/i })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  const region = document.getElementById(toggle.getAttribute('aria-controls') ?? '')
  expect(region).toBeInTheDocument()

  await user.click(toggle)
  expect(screen.getByText('an older one')).toBeInTheDocument()
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  // The same region, still the one named, now holding the list.
  expect(region).toContainElement(screen.getByText('an older one'))
})

it('offers no fold for a project with a single session', async () => {
  // A fold promising no more than the row already shows is a click that
  // changes nothing.
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas')],
      sessions: [session('only', { projectId: ATLAS, firstMessage: 'the only one' })],
    }),
  )

  expect(await screen.findByText('the only one')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /sessions \(/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /all .* sessions/i })).not.toBeInTheDocument()
})
