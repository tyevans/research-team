import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import type { AutonomyRepository } from '@application/ports/repositories.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import type { Route } from '../routing/routes.ts'
import { StreamProvider } from './StreamProvider.tsx'
import { AutonomyLock } from './AutonomyLock.tsx'

const SESSION = SessionId('22222222-2222-2222-2222-222222222222')
const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

/** The spies are returned beside `repo` rather than read back off it, so an
 *  assertion never has to reference a port method as a value -- `unbound-method`
 *  rightly objects to that. `AutonomyPanel.test.tsx` records the same shape for
 *  the same reason. */
const fakeAutonomy = () => {
  const policy = { levels: new Map([['fetch', 'ask']]), gated: ['fetch'] }
  const read = vi.fn<AutonomyRepository['read']>().mockResolvedValue(policy)
  const setLevel = vi.fn<AutonomyRepository['setLevel']>().mockResolvedValue(policy)
  const allowAll = vi
    .fn<AutonomyRepository['allowAll']>()
    .mockResolvedValue({ changed: new Map(), policy })
  const repo: AutonomyRepository = { read, setLevel, allowAll }
  return { repo, read, setLevel }
}

/** Delivers nothing, which is all this suite needs: the project route's
 *  `useProject` subscribes for the frame that moves the holding session, and
 *  only has to subscribe and unsubscribe without throwing. */
const fakeStream = (): EventStream => ({
  connect(_listener: EventStreamListener) {},
  disconnect() {},
})

/** The host is the innermost wrapper, matching the real tree where it sits
 *  inside the providers and outside the page. Without it `Overlay` renders
 *  `null` and every assertion below would fail for a reason that has nothing to
 *  do with the lock. */
const renderLock = (route: Route, parts: Partial<AppContainer>) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={{ stream: fakeStream(), ...parts } as unknown as AppContainer}>
        <StreamProvider>
          <OverlayHost>{children}</OverlayHost>
        </StreamProvider>
      </ContainerProvider>
    </QueryClientProvider>
  )
  return render(<AutonomyLock route={route} />, { wrapper })
}

const HOME: Route = { name: 'home' }

it('reads nothing until it is asked to', async () => {
  // The panel is behind a dialog, so the policy request is too. On a page that
  // never opens it this is the difference between one request per route change
  // and none -- and it is what makes putting the control in the chrome cheap.
  const autonomy = fakeAutonomy()
  renderLock(HOME, { autonomy: autonomy.repo })

  expect(screen.getByRole('button', { name: /without asking/i })).toBeInTheDocument()
  expect(autonomy.read).not.toHaveBeenCalled()
})

it('names itself in text rather than leaving a glyph to be guessed at', () => {
  // S-D2: an icon with no accessible name is a control only a sighted mouse
  // user can identify. The tooltip is a hover affordance and is not this.
  renderLock(HOME, { autonomy: fakeAutonomy().repo })

  const lock = screen.getByRole('button', { name: 'What the agent may do without asking' })
  expect(lock.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
})

it('opens the policy in a dialog, from a route with no project or session', async () => {
  // The whole point of the move: the policy is instance-wide, so it is
  // reachable from the landing page. **Proved red** by rendering the panel
  // without the lock -- the radio is present immediately, and this asserts it
  // is absent until the button is pressed.
  const autonomy = fakeAutonomy()
  renderLock(HOME, { autonomy: autonomy.repo })

  expect(screen.queryByRole('radio')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /without asking/i }))

  expect(await screen.findByText('fetch')).toBeInTheDocument()
  // No session on this route, so there is nothing to record a write against
  // and the panel says so rather than offering controls that would 404.
  expect(screen.getByText(/nothing to record a change against/i)).toBeInTheDocument()
})

it('records a write against the session holding the project being viewed', async () => {
  // The one route that can resolve a holder. A lock that opened read-only on a
  // project page would be a control that never works where it is most wanted,
  // and nothing about it on screen would say why.
  const autonomy = fakeAutonomy()
  renderLock(
    { name: 'project', id: PROJECT, selection: null },
    {
      autonomy: autonomy.repo,
      projects: {
        project: vi.fn().mockResolvedValue({ id: PROJECT, name: 'p', activeSessionId: SESSION }),
      } as unknown as AppContainer['projects'],
    },
  )

  await userEvent.click(screen.getByRole('button', { name: /without asking/i }))
  await userEvent.click(await screen.findByRole('radio', { name: 'auto' }))

  expect(autonomy.setLevel).toHaveBeenCalledWith(SESSION, 'fetch', 'auto')
})

it('closes, and the policy goes with it', async () => {
  renderLock(HOME, { autonomy: fakeAutonomy().repo })

  await userEvent.click(screen.getByRole('button', { name: /without asking/i }))
  await screen.findByText('fetch')
  await userEvent.click(screen.getByRole('button', { name: 'Close' }))

  expect(screen.queryByText('fetch')).not.toBeInTheDocument()
})
