import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'
import type { Roster } from '@domain/worker/worker.ts'

import { Workers } from './Workers.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')
const SESSION = SessionId('22222222-2222-2222-2222-222222222222')

const empty: Roster = { projectId: PROJECT, workers: [], idleSessionIds: [] }

/** Mirrors `use-attempts.test.tsx`'s harness: a fake container behind the same
 *  providers the real app wraps every view in, plus a `QueryClient` this file
 *  keeps a handle to so `triggerRefetch` can invalidate the polled query. */
const renderWithContainer = (ui: ReactElement, parts: Partial<AppContainer>) => {
  const container = parts as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>{children}</ContainerProvider>
    </QueryClientProvider>
  )
  return { ...render(ui, { wrapper }), client }
}

/** Forces the polled query to run again and fail, without waiting on the real
 *  2s interval. Invalidating on the `QueryClient` this test created is
 *  deterministic — a fake-timer advance would also work, but would tie the
 *  test to the panel's exact `POLL_MS` and add fake-timer/`waitFor` interplay
 *  this file does not otherwise need. */
const triggerRefetch = async (client: QueryClient) => {
  await client.invalidateQueries()
}

it('names the work in flight and offers it as a button', async () => {
  const workers = {
    on: vi.fn().mockResolvedValue({
      ...empty,
      workers: [
        {
          kind: 'turn' as const,
          ref: SESSION,
          detail: 'turn 12',
          sessionId: SESSION,
          parent: null,
          startedAt: null,
        },
      ],
    }),
  }

  renderWithContainer(<Workers projectId={PROJECT} watching={null} onWatch={() => {}} />, {
    workers,
  })

  expect(await screen.findByText('turn 12')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /turn 12/ })).toBeInTheDocument()
})

it('says nothing is running rather than showing an empty box', async () => {
  const workers = { on: vi.fn().mockResolvedValue(empty) }

  renderWithContainer(<Workers projectId={PROJECT} watching={null} onWatch={() => {}} />, {
    workers,
  })

  expect(await screen.findByText(/nothing is running/i)).toBeInTheDocument()
})

it('keeps the last roster and marks it stale when a poll fails', async () => {
  // The load-bearing case. Emptying the panel on a failed poll would say
  // "nothing is running", which is the exact lie this panel exists to kill.
  const workers = {
    on: vi
      .fn()
      .mockResolvedValueOnce({
        ...empty,
        workers: [
          {
            kind: 'run' as const,
            ref: 'run-1',
            detail: 'autonomous run',
            sessionId: SESSION,
            parent: null,
            startedAt: null,
          },
        ],
      })
      .mockRejectedValue(new Error('network')),
  }

  const { client } = renderWithContainer(
    <Workers projectId={PROJECT} watching={null} onWatch={() => {}} />,
    { workers },
  )

  expect(await screen.findByText('autonomous run')).toBeInTheDocument()

  await triggerRefetch(client)

  await waitFor(() => expect(screen.getByText(/stale/i)).toBeInTheDocument())
  expect(screen.getByText('autonomous run')).toBeInTheDocument()
})

it('indents a nested extraction under its parent', async () => {
  const workers = {
    on: vi.fn().mockResolvedValue({
      ...empty,
      workers: [
        {
          kind: 'run' as const,
          ref: 'run-1',
          detail: 'autonomous run',
          sessionId: SESSION,
          parent: null,
          startedAt: null,
        },
        {
          kind: 'extraction' as const,
          ref: 'src-1',
          detail: 'consolidating 7/23',
          sessionId: null,
          parent: 'run-1',
          startedAt: null,
        },
      ],
    }),
  }

  renderWithContainer(<Workers projectId={PROJECT} watching={null} onWatch={() => {}} />, {
    workers,
  })

  const nested = await screen.findByText('consolidating 7/23')
  expect(nested.closest('.worker-child')).not.toBeNull()
})
