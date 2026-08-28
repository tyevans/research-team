import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'

import type { EventStreamListener } from '@application/ports/event-stream.ts'
import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { WorkerRepository } from '@application/ports/repositories.ts'

import { StreamProvider } from '../shell/StreamProvider.tsx'
import { ROSTER_POLL_MS, useRunningAgents } from './use-running-agents.ts'

/** A stream that never emits, standing in for the SSE connection `useStream`
 *  requires -- `useFrameRefresh` inside the hook under test needs a provider,
 *  not any frames. Copied from `AgentWidget.test.tsx`'s `fakeStream`. */
const fakeStream = () => ({
  connect: (_l: EventStreamListener) => {},
  disconnect: () => {},
})

/** Mirrors `Workers.test.tsx`'s harness: a fake container behind the same
 *  `QueryClientProvider` + `ContainerProvider` pair every view renders inside,
 *  built as a partial container and cast -- the established pattern here. */
const renderHookWithContainer = <Props, Result>(
  hook: (props: Props) => Result,
  options: { initialProps: Props; everywhere: WorkerRepository['everywhere'] },
) => {
  const parts: Partial<AppContainer> = {
    workers: { everywhere: options.everywhere, on: vi.fn() } as unknown as WorkerRepository,
    projects: { list: vi.fn().mockResolvedValue([]) } as unknown as AppContainer['projects'],
    stream: fakeStream(),
  }
  const container = parts as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <StreamProvider>{children}</StreamProvider>
      </ContainerProvider>
    </QueryClientProvider>
  )
  return renderHook(hook, { wrapper, initialProps: options.initialProps })
}

afterEach(() => {
  vi.useRealTimers()
})

/** The one liveness case no frame can reveal.
 *
 * `Workers.tsx` recorded this before it was deleted, with
 * `tests/integration/test_turn_visibility.py::test_a_turns_events_all_become_visible_at_once`
 * behind it: a turn's events append atomically when the turn commits, so while
 * a turn is running the feed carries nothing about it at all. A turn worker is
 * in the roster for exactly the interval in which no frame can arrive. A
 * frame-driven refresh would therefore show a turn only after it had gone.
 *
 * Open, this polls. Closed, it must not — the collapsed dock draws a count, and
 * a poll on every page of an idle console is the cost this design moved off the
 * project page rather than spreading.
 */
it('polls the roster while the dock is open and not while it is closed', async () => {
  vi.useFakeTimers()
  const everywhere = vi.fn().mockResolvedValue([])

  const { rerender } = renderHookWithContainer(
    ({ open }: { open: boolean }) => useRunningAgents(open),
    {
      initialProps: { open: false },
      everywhere,
    },
  )

  await vi.advanceTimersByTimeAsync(ROSTER_POLL_MS * 3)
  expect(everywhere).toHaveBeenCalledTimes(1)

  rerender({ open: true })
  await vi.advanceTimersByTimeAsync(ROSTER_POLL_MS * 3)
  expect(everywhere.mock.calls.length).toBeGreaterThan(1)

  vi.useRealTimers()
})
