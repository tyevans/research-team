/** The one case `DecisionBar.test.tsx` cannot exercise: a decision reached
 *  for an approval this tab never saw `approvalRequested` for. `latency_ms`
 *  is required and non-optional in the domain schema, so there is no honest
 *  value to send -- the guard has to skip the whole kind, not send a
 *  fabricated zero.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { InteractionLogContext } from '@app/interaction-log-provider.tsx'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import type { ApprovalRepository } from '@application/ports/repositories.ts'
import { ApprovalId, SessionId } from '@domain/shared/identifier.ts'

import { StreamProvider } from './StreamProvider.tsx'
import { useApprovalFeed } from './use-approval-feed.ts'

const controllableStream = () => {
  let listener: EventStreamListener | null = null
  const stream: EventStream = {
    connect: (l) => {
      listener = l
    },
    disconnect: () => {
      listener = null
    },
  }
  return {
    stream,
    deliver(...frames: Parameters<EventStreamListener['onFrame']>[0][]) {
      act(() => {
        for (const frame of frames) listener?.onFrame(frame)
      })
    },
  }
}

it('records no ApprovalDecided when the decision is reached for an approval this tab never saw shown', async () => {
  const record = vi.fn()
  const decide = vi.fn<ApprovalRepository['decide']>().mockResolvedValue(undefined)
  const approvals: ApprovalRepository = {
    pending: vi.fn<ApprovalRepository['pending']>().mockResolvedValue([]),
    decide,
  }
  const feed = controllableStream()
  const container = { approvals, stream: feed.stream } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })

  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <InteractionLogContext.Provider value={{ record } as never}>
          <StreamProvider>{children}</StreamProvider>
        </InteractionLogContext.Provider>
      </ContainerProvider>
    </QueryClientProvider>
  )

  const { result } = renderHook(() => useApprovalFeed(), { wrapper })

  // No `approvalRequested` delivered at all -- unlike a normal card, which is
  // how this state is reached in practice (a settle racing a mount, or a
  // reconnect landing mid-decision). `decide` is called directly because
  // nothing rendered ever put this approval on screen.
  const sessionId = SessionId('11111111-1111-1111-1111-111111111111')
  const approval = {
    id: ApprovalId('a-never-shown'),
    sessionId,
    toolName: 'fetch',
    description: null,
    args: {},
    allowedDecisions: ['approve', 'edit', 'reject'] as const,
    context: null,
  }

  act(() => {
    result.current.decide(approval, { decision: 'approve' }, false)
  })

  await waitFor(() => {
    expect(decide).toHaveBeenCalled()
  })
  expect(record).not.toHaveBeenCalledWith('ApprovalDecided', expect.anything())
})
