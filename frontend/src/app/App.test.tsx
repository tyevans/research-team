import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
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
      join: vi.fn(),
      delete: vi.fn().mockResolvedValue(undefined),
    },
    research: { current: vi.fn().mockResolvedValue(null) },
    workers: { on: vi.fn().mockResolvedValue({ workers: [], idleSessionIds: [] }) },
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
