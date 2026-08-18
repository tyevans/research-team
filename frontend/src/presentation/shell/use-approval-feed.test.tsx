/** What `DecisionBar.test.tsx` cannot exercise from the rendered bar: a
 *  decision reached for an approval this tab never saw `approvalRequested`
 *  for, and the backgrounded-time correction on `hidden_ms`.
 *
 *  The first test here is purely negative and **would pass against a build
 *  that never emits `ApprovalDecided` at all** -- said out loud per the
 *  repo's convention. Its constraining pair is `DecisionBar.test.tsx`, which
 *  pins the positive emission and its `latency_ms`; the second test below now
 *  also constrains this file directly.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { InteractionLogContext } from '@app/interaction-log-provider.tsx'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import type { ApprovalRepository } from '@application/ports/repositories.ts'
import { ApprovalId, SessionId } from '@domain/shared/identifier.ts'

import { StreamProvider } from './StreamProvider.tsx'
import { useApprovalFeed } from './use-approval-feed.ts'

afterEach(() => {
  vi.useRealTimers()
})

/** Drive `document.visibilityState`, which is a getter with no setter. */
const visibility = (state: 'hidden' | 'visible') => {
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue(state)
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'))
  })
}

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

/** `latency_ms` counts wall time and `hidden_ms` says how much of it the tab
 *  was backgrounded for. Gated calls arrive while the reader is elsewhere, so
 *  an approval that waits through a lunch break and is answered on return
 *  would otherwise report an hour of "deliberation" -- the split this kind
 *  exists for, decided by a number that cannot make it.
 */
it('reports the backgrounded portion of the wait as hidden_ms', async () => {
  vi.useFakeTimers()
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

  const approval = {
    id: ApprovalId('a-hidden'),
    sessionId: SessionId('11111111-1111-1111-1111-111111111111'),
    toolName: 'fetch',
    description: null,
    args: {},
    allowedDecisions: ['approve', 'edit', 'reject'] as const,
    context: null,
  }
  feed.deliver({ kind: 'approvalRequested', approval } as never)

  visibility('hidden')
  vi.advanceTimersByTime(60_000)
  visibility('visible')
  vi.advanceTimersByTime(2_000)

  act(() => {
    result.current.decide(approval, { decision: 'approve' }, false)
  })
  await vi.waitFor(() => {
    expect(record).toHaveBeenCalledWith('ApprovalDecided', expect.anything())
  })

  const payload = record.mock.calls.find(([kind]) => kind === 'ApprovalDecided')?.[1] as {
    latency_ms: number
    hidden_ms: number
  }
  expect(payload.latency_ms).toBeGreaterThanOrEqual(62_000)
  expect(payload.hidden_ms).toBeGreaterThanOrEqual(60_000)
  // The deliberation the reader actually did. Without `hidden_ms` this card is
  // indistinguishable from a minute of careful reading.
  expect(payload.latency_ms - payload.hidden_ms).toBeLessThan(5_000)
})
