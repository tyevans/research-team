import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'

/** The landing view, replaced by one that throws during render.
 *
 * A file of its own rather than a case in `App.test.tsx` because `vi.mock` is
 * hoisted to module scope: a throwing `TreeView` in that file would break the
 * fifteen tests that render the landing page for other reasons.
 *
 * Mocking a view is a blunt instrument and the alternative was worse. The
 * class of error this boundary exists for -- a session claim of an
 * unanticipated shape, a settings payload with a null where an object was
 * assumed -- has no representative in the tree today, which is the whole
 * reason the boundary is being built *before* those land. A view that throws
 * is the honest stand-in: React does not care which component threw.
 */
vi.mock('@presentation/tree/TreeView.tsx', () => ({
  TreeView: () => {
    throw new TypeError("cannot read properties of undefined (reading 'name')")
  },
}))

const NOW = Date.parse('2026-08-09T12:00:00Z')

let interactions = { send: vi.fn(), sendOnUnload: vi.fn() }

const container = () =>
  ({
    now: () => NOW,
    interactions,
    preferences: new InMemoryPreferenceStore(),
    stream: { connect: vi.fn(), disconnect: vi.fn() },
    sessions: { list: vi.fn().mockResolvedValue([]), tree: vi.fn().mockResolvedValue([]) },
    projects: { list: vi.fn().mockResolvedValue([]) },
    workers: { all: vi.fn().mockResolvedValue([]) },
    // Identity switched off, which is `AGENT_AUTH`'s default and the state
    // this file is about. Present rather than omitted for the reason
    // `App.test.tsx` states beside its own copy: this object ends in an `as
    // unknown as AppContainer`, so a missing key is `undefined` at runtime and
    // `App`'s auth gate would call `.status()` on it -- a `TypeError` inside a
    // query rather than a compile error, caught by React Query and therefore
    // invisible except as a test that becomes timing-sensitive.
    auth: {
      status: vi
        .fn()
        .mockResolvedValue({ authRequired: false, authenticated: false, configured: false }),
      me: vi.fn(),
      loginHref: vi.fn().mockReturnValue('/auth/login'),
      logoutHref: vi.fn().mockReturnValue('/auth/logout'),
    },
  }) as unknown as AppContainer

beforeEach(() => {
  window.location.hash = ''
  interactions = { send: vi.fn(), sendOnUnload: vi.fn() }
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  vi.restoreAllMocks()
})

const renderApp = async () => {
  const { App } = await import('./App.tsx')
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container()}>{children}</ContainerProvider>
    </QueryClientProvider>
  )
  return render(<App />, { wrapper })
}

it('keeps the console on screen when a view throws during render', async () => {
  /** Before this change the same render left `#root` empty: React unmounts
   *  the whole tree for an uncaught render throw, and there was no boundary
   *  anywhere in `frontend/src`. Proved red by removing `<ErrorBoundary>` and
   *  `<LoggedErrorBoundary>` from `App.tsx` -- the render throws out of
   *  `render()` and this file fails at the first line of every test. */
  await renderApp()

  expect(await screen.findByRole('alert')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
})

it('leaves the chrome standing, so there is a way out that is not the boundary', async () => {
  /** This is why the boundary is inside `Shell` rather than around it. An
   *  earlier draft wrapped `Shell`, and the fallback replaced the header with
   *  it -- leaving the brand link, the log link and the breadcrumb gone at
   *  exactly the moment a reader wants somewhere else to be. Move the
   *  boundary back outside `Shell` and this test fails; the two above still
   *  pass, which is what makes it worth writing separately. */
  await renderApp()
  await screen.findByRole('alert')

  expect(screen.getByRole('link', { name: /research.team/ })).toBeInTheDocument()
})

it('records the render error into the interaction log, as far as the sink', async () => {
  /** The assertion is a row that reached the sink. An assertion that the
   *  console "did not crash" passes with the whole reporting path deleted --
   *  the context default records nothing and fails at nothing. */
  const { unmount } = await renderApp()
  await screen.findByRole('alert')
  unmount()
  await waitFor(() => expect(interactions.sendOnUnload).toHaveBeenCalled())

  const batch = interactions.sendOnUnload.mock.calls[0]?.[0] as unknown as {
    kind: string
    view: string
    payload: Record<string, unknown>
  }[]
  const raised = batch.find((event) => event.kind === 'RenderErrorRaised')

  // The view the envelope carries, not the boundary's `where`: those are two
  // different questions and both matter -- which page failed, and which
  // boundary caught it.
  expect(raised?.view).toBe('home')
  expect(raised?.payload).toEqual({
    where: 'console',
    error_name: 'TypeError',
    message_length: "cannot read properties of undefined (reading 'name')".length,
  })
})
