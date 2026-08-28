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
  // The two write ports are taken as arguments rather than read back off the
  // built container. `@typescript-eslint/unbound-method` rejects
  // `expect(container.projects.join)` -- a method reference plucked off an
  // object -- and it is right to: the assertion wants the spy, and the spy is
  // what a caller can hold. Same shape as `use-project.test.tsx`, which holds
  // its `project` mock in a local const for the same reason.
  join = vi.fn(),
  del = vi.fn().mockResolvedValue(undefined),
  ...rest
}: {
  projects?: readonly Project[]
  sessions?: readonly SessionSummary[]
  tree?: readonly SessionSummary[]
  join?: ReturnType<typeof vi.fn>
  del?: ReturnType<typeof vi.fn>
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
      join,
      delete: del,
    },
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

/** Every destination the row still offers, and the two it no longer does.
 *
 * **This asserted four buttons and now asserts one link and one menu.** It
 * used to click `Resume 3f2a…`, then `Project`, then `Ask`, then `New
 * session`, which is the measurement this redesign is a response to: the
 * project page — what the whole console hangs off — was the *third* target on
 * a row of eight, in the secondary tone, past a flex spacer, while the largest
 * thing on the row (the name) was an inert `<span>` because `ProjectCard`'s
 * `href` was optional and `ProjectList` never passed it.
 *
 * The name is a real `<a>` now, so this asserts an `href` rather than a click:
 * ⌘-click, middle-click and copy-link all work, and none of them did.
 * L-§9.3 named that gap ("Nothing on the page is a link") and it survived the
 * whole of the last rework of this page.
 */
it('reaches the project page from the row’s name, as a link', async () => {
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas', { activeSessionId: HOLDER })],
      sessions: [session('a', { projectId: ATLAS })],
    }),
  )

  expect(await screen.findByRole('link', { name: 'atlas' })).toHaveAttribute('href', `#/p/${ATLAS}`)
})

it('reaches the ask page, which no tab on the project view can reach', async () => {
  // `App.tsx` intercepts the `ask` facet above `ProjectView` and renders a
  // page of its own, so it genuinely cannot be reached by opening the project
  // and clicking a MATERIAL tab. It is in the menu rather than on the row
  // because the row is one verb now, and this is not that verb -- but it still
  // needs a door, which is the one thing kept verbatim from the button it
  // replaces.
  const user = userEvent.setup()
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas')],
      sessions: [session('a', { projectId: ATLAS })],
    }),
  )

  await user.click(await screen.findByRole('button', { name: /More actions for atlas/ }))
  await user.click(screen.getByRole('menuitem', { name: 'Ask' }))
  expect(window.location.hash).toBe(`#/p/${ATLAS}/ask`)
})

/** One verb, and it does not name a session or ask about one.
 *
 * **This replaces `Resume 3f2a…` / `New session` / `Open`.** A held project
 * offered two buttons and a confirmation dialog; a free one offered a third
 * label for the same intent. All three were the reader resolving a lock before
 * they had read anything, in a vocabulary — holding, taking over — that is
 * about where the next write goes.
 *
 * `Continue` resolves it instead, from a field the reader never sees: the
 * holder's transcript when there is one, a fresh session when there is not.
 * Both arms are asserted here because the branch is invisible from the
 * outside, which is exactly what makes it worth a test.
 */
it('continues a held project into the session already open, without a dialog', async () => {
  const user = userEvent.setup()
  const join = vi.fn()
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas', { activeSessionId: HOLDER })],
      sessions: [session('a', { projectId: ATLAS })],
      join,
    }),
  )

  await user.click(await screen.findByRole('button', { name: 'Continue' }))

  expect(window.location.hash).toBe(`#/s/${HOLDER}`)
  // No write, and no confirmation. Taking over -- ending somebody's session --
  // is not something an index offers.
  expect(join).not.toHaveBeenCalled()
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.queryByRole('button', { name: 'New session' })).toBeNull()
  expect(screen.queryByRole('button', { name: /Resume/ })).toBeNull()
})

it('continues a free project by starting a session in it', async () => {
  const user = userEvent.setup()
  const join = vi.fn().mockResolvedValue({
    sessionId: SessionId('99999999-9999-9999-9999-999999999999'),
    warning: null,
  })
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(SANDBOX, 'sandbox')],
      sessions: [session('a', { projectId: SANDBOX })],
      join,
    }),
  )

  await user.click(await screen.findByRole('button', { name: 'Continue' }))

  // `false`, always: the take-over flag has no call site on this page any more.
  expect(join).toHaveBeenCalledWith(SANDBOX, false)
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
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(SANDBOX, 'sandbox')],
      sessions: [session('a', { projectId: SANDBOX })],
    }),
  )

  const toProject = await screen.findByRole('link', { name: 'sandbox' })
  expect(toProject).not.toHaveAttribute('aria-disabled')
  expect(toProject).toHaveAttribute('href', `#/p/${SANDBOX}`)
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
  const user = userEvent.setup()
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas')],
      sessions: [session('a', { projectId: ATLAS })],
    }),
  )

  expect(await screen.findByRole('link', { name: 'atlas' })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /More actions for atlas/ }))
  expect(screen.getByRole('menuitem', { name: 'Ask' })).toBeInTheDocument()

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
      workers: { on: vi.fn().mockRejectedValue(new Error('no roster')) },
    }),
  )

  expect(await screen.findByText('atlas')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled()
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
  // The warning survives; the short id inside it does not. A reader about to
  // destroy something is entitled to know that a session in progress ends with
  // it. *Which* session is not a choice they are being offered, and it was the
  // last place on this page a holder was named.
  expect(
    within(dialog).getByText(/A session is still holding it, and will be ended first/),
  ).toBeInTheDocument()
  expect(within(dialog).queryByText(new RegExp(HOLDER.slice(0, 8)))).toBeNull()
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

/** **The one place heldness is still load-bearing on this page, pinned.**
 *
 * `DELETE /api/projects/{id}` refuses a held project unless
 * `release_holder=true`, and the client passes `isHeld(project)` for that flag.
 * Nothing on the page draws the holder any more, so this argument is the shape
 * that rots silently: a `false` here fails against exactly the projects a
 * person is most likely to delete — the one they were last working in — and the
 * only symptom is a request that does not succeed.
 *
 * **Nothing checked it while the holder was on screen**, which is the reason it
 * is written now rather than then. `CLAUDE.md`'s rule about a "background
 * concern" not becoming "silently absent" is about exactly this: the drawing
 * can go, the fact cannot, and the assertion is what tells the difference.
 *
 * **Proved red** by hard-coding `false` at the call site: `expected [id, true],
 * received [id, false]`.
 */
it('still ends the holding session when a held project is deleted', async () => {
  const user = userEvent.setup()
  const del = vi.fn().mockResolvedValue(undefined)
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas', { activeSessionId: HOLDER })],
      sessions: [session('a', { projectId: ATLAS })],
      del,
    }),
  )

  await user.click(await screen.findByRole('button', { name: /More actions for atlas/ }))
  await user.click(screen.getByRole('menuitem', { name: 'Delete' }))
  await user.click(await screen.findByRole('button', { name: 'Delete project' }))

  expect(del).toHaveBeenCalledWith(ATLAS, true)
})

/** The other half of the pair.
 *
 *  A test that only asserted `true` would pass against a call site that had
 *  stopped reading the project at all and always sent `true` — which would
 *  silently end sessions through a route whose entire purpose is to refuse to.
 *  Two arms, because one arm cannot tell a branch from a constant. */
it('does not force the flag for a project nothing is holding', async () => {
  const user = userEvent.setup()
  const del = vi.fn().mockResolvedValue(undefined)
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(SANDBOX, 'sandbox')],
      sessions: [session('a', { projectId: SANDBOX })],
      del,
    }),
  )

  await user.click(await screen.findByRole('button', { name: /More actions for sandbox/ }))
  await user.click(screen.getByRole('menuitem', { name: 'Delete' }))
  await user.click(await screen.findByRole('button', { name: 'Delete project' }))

  expect(del).toHaveBeenCalledWith(SANDBOX, false)
})

/** The holder is nowhere on the page, in any of its four spellings.
 *
 *  It had four: `held by 3f2a…` in the card's head, the word `free` beside it,
 *  a `held` chip on the previewed session row, and `Resume 3f2a…` as the row's
 *  primary verb. All four are gone, and this is the single assertion that fails
 *  if any one of them comes back — worth more than four separate absences,
 *  because the failure this guards against is a future change re-deriving the
 *  concept somewhere new rather than reverting a line.
 *
 *  What it deliberately does *not* claim: that the holder is unknown. The
 *  fixture is a held project, `currentSession` still prefers the holder when
 *  choosing what to preview, and the two tests above pin the `force` flag. */
it('says nothing about which session is holding a project', async () => {
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas', { activeSessionId: HOLDER })],
      sessions: [session(HOLDER, { projectId: ATLAS, firstMessage: 'the one still open' })],
    }),
  )

  expect(await screen.findByText('the one still open')).toBeInTheDocument()
  expect(screen.queryByText('held by')).toBeNull()
  expect(screen.queryByText('free')).toBeNull()
  expect(screen.queryByText('held')).toBeNull()
  expect(screen.queryByRole('button', { name: /Resume/ })).toBeNull()
})

/** Escape gives the page back, which two keystrokes used to.
 *
 *  `type="search"` clears on Escape in WebKit and in no other engine, and even
 *  there it leaves focus in a box the reader has finished with. Changing your
 *  mind about a filter is the commonest way out of a search and it was the most
 *  expensive: select-all, delete, then Tab or a click. */
it('clears the search and gives focus back on Escape', async () => {
  const user = userEvent.setup()
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas'), project(SANDBOX, 'sandbox')],
      sessions: [session('a', { projectId: ATLAS }), session('b', { projectId: SANDBOX })],
    }),
  )

  await screen.findByText('atlas')
  const box = screen.getByLabelText(/search projects/i)
  await user.type(box, 'atlas')
  expect(screen.queryByText('sandbox')).toBeNull()

  await user.keyboard('{Escape}')

  expect(box).toHaveValue('')
  expect(box).not.toHaveFocus()
  expect(screen.getByText('sandbox')).toBeInTheDocument()
})

/** Recency headings label the list, and label nothing over a set of results.
 *
 *  There is a second reason and it is the load-bearing one: `itemKey`'s
 *  uniqueness rests on each band opening exactly once, which holds only because
 *  the ranked input is sorted by band. Anything that reorders results — a
 *  relevance rank, the obvious next thing to want from this search — would emit
 *  a band twice, and a duplicate key is one measurement cell holding two rows'
 *  heights. Dropping the headings removes the precondition rather than relying
 *  on it. */
it('drops the recency headings while a search is running', async () => {
  const user = userEvent.setup()
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas'), project(SANDBOX, 'sandbox')],
      sessions: [session('a', { projectId: ATLAS }), session('b', { projectId: SANDBOX })],
    }),
  )

  expect(await screen.findByText('Today')).toBeInTheDocument()

  await user.type(screen.getByLabelText(/search projects/i), 'atlas')
  expect(screen.queryByText('Today')).toBeNull()
  expect(screen.getByText('atlas')).toBeInTheDocument()
})

/** What the top of the page no longer costs.
 *
 *  A two-sentence, non-dismissible paragraph explaining what a project is, and
 *  an `<h2>` reading "Projects" over the only list on the page. Both are read
 *  once and were rendered on every visit, and together they pushed the first
 *  row down by about a third of the fold on a laptop. The paragraph is not
 *  deleted — it is on the first-run page, asserted by the first test in this
 *  file, which is where somebody is genuinely reading it for the first time. */
it('does not re-explain itself to a returning reader', async () => {
  renderPage(
    <TreeView />,
    containerWith({
      projects: [project(ATLAS, 'atlas')],
      sessions: [session('a', { projectId: ATLAS })],
    }),
  )

  expect(await screen.findByText('atlas')).toBeInTheDocument()
  expect(screen.queryByText(/outlives one conversation/i)).toBeNull()
  expect(screen.queryByRole('heading', { name: 'Projects' })).toBeNull()
})
