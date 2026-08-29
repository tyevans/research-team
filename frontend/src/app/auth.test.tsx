import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { App } from '@app/App.tsx'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Container as AppContainer } from '@app/container.ts'
import type { AuthStatus, Principal } from '@application/ports/repositories.ts'
import { ApiError } from '@application/ports/errors.ts'
import { HttpClient } from '@infrastructure/http/http-client.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'

/** The sign-in wall and the account menu, rendered through the real `App`.
 *
 * Through `App` rather than through the components directly, because the
 * question that matters is composition. `LoginScreen` renders in isolation
 * whether or not anything ever chooses to show it, and an `AccountMenu` test
 * passes against a console that never mounts one -- which is exactly the hole
 * `App.test.tsx`'s own docstring describes for overlays.
 *
 * The one thing asserted hardest is the *default*: with `AGENT_AUTH` off, this
 * wrapper must be invisible. Five other branches of the user-system plan are
 * built against that.
 */

const ADA: Principal = {
  subject: 'zitadel-1',
  tenantId: 'org-1',
  email: 'ada@example.test',
  displayName: 'Ada Lovelace',
  avatarUrl: '',
  firstSeenAt: '2026-08-01T00:00:00Z',
  lastSeenAt: '2026-08-29T00:00:00Z',
  mirrored: true,
}

const OFF: AuthStatus = { authRequired: false, authenticated: false, configured: false }

/** The container, and the auth spies inside it, handed back separately.
 *
 * Two return values rather than reaching for `container.auth.status` at the
 * assertion, because this repository's lint forbids that: passing a method
 * reference around detached from its object is `@typescript-eslint/unbound-method`,
 * and the rule is right in general even though `vi.fn()` has no `this`. */
const containerWith = (status: AuthStatus, person: Principal | null = null) => {
  const auth = {
    status: vi.fn().mockResolvedValue(status),
    me: person
      ? vi.fn().mockResolvedValue(person)
      : vi.fn().mockRejectedValue(new ApiError('not signed in', 401)),
    loginHref: vi.fn((next: string) => `/auth/login?next=${encodeURIComponent(next)}`),
    logoutHref: vi.fn().mockReturnValue('/auth/logout'),
  }
  const container = {
    // Only what the auth path touches. Everything else is a `vi.fn()` that
    // resolves to nothing, which is enough because none of these tests looks
    // at a pane's contents -- the assertions are all about the chrome and
    // about which of the two top-level trees rendered.
    stream: { connect: vi.fn(), disconnect: vi.fn() },
    sessions: { list: vi.fn().mockResolvedValue([]), tree: vi.fn().mockResolvedValue([]) },
    projects: { list: vi.fn().mockResolvedValue([]), create: vi.fn(), delete: vi.fn() },
    workspace: { tree: vi.fn().mockResolvedValue({ nodes: [] }) },
    workers: { everywhere: vi.fn().mockResolvedValue([]) },
    extractions: { on: vi.fn().mockResolvedValue({ current: [], last: [] }) },
    health: {
      summaries: vi.fn().mockResolvedValue({ healthy: true, following: true, failedEvents: 0 }),
      rebuildSummaries: vi.fn(),
    },
    autonomy: { read: vi.fn().mockResolvedValue({ mode: 'ask' }), set: vi.fn() },
    // The real store rather than two `vi.fn()`s: the shell reads several
    // preferences during its first render, and a stub that answers
    // `undefined` to one of them crashes in a `useState` initialiser rather
    // than anywhere that names a preference.
    preferences: new InMemoryPreferenceStore(),
    interactions: { send: vi.fn(), sendOnUnload: vi.fn() },
    now: () => 0,
    auth,
  } as unknown as AppContainer
  return { container, auth }
}

const renderApp = (container: AppContainer) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
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

it('with auth off, renders the console and never asks who is signed in', async () => {
  const { container, auth } = containerWith(OFF)
  renderApp(container)

  // The console, not the wall. `main` is `Shell`'s landmark and `LoginScreen`
  // renders one too, so this is asserted on the sign-in button's *absence*
  // rather than on a landmark that both trees have.
  await waitFor(() => expect(auth.status).toHaveBeenCalled())
  expect(screen.queryByRole('link', { name: 'Sign in' })).toBeNull()
  // `/api/me` must not be requested at all. A console that asked anyway would
  // put a 401 in the network log of every instance with no identity provider,
  // which is noise that makes a real one impossible to spot.
  expect(auth.me).not.toHaveBeenCalled()
})

it('with auth required and no session, replaces the console with the sign-in wall', async () => {
  const { container } = containerWith({
    authRequired: true,
    authenticated: false,
    configured: true,
  })
  renderApp(container)

  const signIn = await screen.findByRole('link', { name: 'Sign in' })
  expect(signIn).toHaveAttribute('href', expect.stringContaining('/auth/login'))
  expect(screen.getByRole('link', { name: 'Create an account' })).toBeTruthy()
  // The console's own chrome is gone, not merely covered. The brand link home
  // is on every route of the real shell and on none of this one.
  expect(screen.queryByRole('link', { name: /research/i })).toBeNull()
})

it('carries the current location into the sign-in link', async () => {
  window.location.hash = '#/p/abc'
  const { container, auth } = containerWith({
    authRequired: true,
    authenticated: false,
    configured: true,
  })
  renderApp(container)

  await screen.findByRole('link', { name: 'Sign in' })
  // Asserted on the argument rather than on the href, because building the URL
  // is the repository's job and the server is what validates it. What this
  // console is responsible for is *passing where you were*, and a build that
  // sent everybody to `/` would look identical on screen.
  expect(auth.loginHref).toHaveBeenCalledWith(expect.stringContaining('#/p/abc'))
})

it('says so when auth is required and no provider is configured', async () => {
  renderApp(
    containerWith({ authRequired: true, authenticated: false, configured: false }).container,
  )

  await screen.findByText(/No identity provider is configured/)
  // No sign-in button, because it would navigate to a 503 -- which reads as
  // the provider being down rather than absent.
  expect(screen.queryByRole('link', { name: 'Sign in' })).toBeNull()
})

it('shows the signed-in person in the chrome, with a way out', async () => {
  const { container } = containerWith(
    { authRequired: true, authenticated: true, configured: true },
    ADA,
  )
  renderApp(container)

  const trigger = await screen.findByRole('button', { name: 'Signed in as Ada Lovelace' })
  await userEvent.click(trigger)

  // The email is in the menu and not on the trigger: the chrome is dense, and
  // the name is what tells two accounts apart.
  expect(await screen.findByText('ada@example.test')).toBeTruthy()
  expect(screen.getByRole('menuitem', { name: 'Sign out' })).toBeTruthy()
})

it('signs out by navigating, not by changing a route', async () => {
  const assign = vi.fn()
  vi.spyOn(window, 'location', 'get').mockReturnValue({
    ...window.location,
    assign,
    hash: '',
    pathname: '/',
  })

  const { container } = containerWith(
    { authRequired: true, authenticated: true, configured: true },
    ADA,
  )
  renderApp(container)

  await userEvent.click(await screen.findByRole('button', { name: 'Signed in as Ada Lovelace' }))
  await userEvent.click(await screen.findByRole('menuitem', { name: 'Sign out' }))

  // A `navigate()` would leave the cookie in place and the person signed in,
  // with a UI insisting otherwise -- and this is the only assertion that can
  // tell the two apart, because both make the menu close.
  await waitFor(() => expect(assign).toHaveBeenCalledWith('/auth/logout'))
})

it('reports the first 401 once, however many requests fail together', async () => {
  const unauthorized = vi.fn()
  const client = new HttpClient('', unauthorized)
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'not signed in' }), {
        status: 401,
        headers: { 'content-type': 'application/json' },
      }),
    ),
  )

  await Promise.all(
    // Five, because one would pass against a client with no latch at all. A
    // cookie that expires with a page open fails every in-flight request, and
    // without the latch the browser is told to navigate once per failure.
    // A real schema rather than a stand-in: the 401 is raised before decoding,
    // so which schema it is does not matter, and a hand-rolled object would
    // need an `any` to satisfy the signature.
    [0, 1, 2, 3, 4].map(() => client.get('/api/sessions', z.null()).catch(() => undefined)),
  )

  expect(unauthorized).toHaveBeenCalledTimes(1)
  vi.unstubAllGlobals()
})
