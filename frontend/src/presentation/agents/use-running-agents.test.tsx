import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'

import type { EventStreamListener, FeedFrame } from '@application/ports/event-stream.ts'
import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { WorkerRepository } from '@application/ports/repositories.ts'

import { StreamProvider } from '../shell/StreamProvider.tsx'
import { IDLE_ROSTER_POLL_MS, ROSTER_POLL_MS, useRunningAgents } from './use-running-agents.ts'

/** A stream that never emits, standing in for the SSE connection `useStream`
 *  requires -- `useFrameRefresh` inside the hook under test needs a provider,
 *  not any frames. Copied from `AgentWidget.test.tsx`'s `fakeStream`. */
const fakeStream = () => ({
  connect: (_l: EventStreamListener) => {},
  disconnect: () => {},
})

/** A stream that hands its listener back, so a test can push one frame. */
const drivableStream = () => {
  let listener: EventStreamListener | null = null
  return {
    stream: {
      connect: (l: EventStreamListener) => {
        listener = l
      },
      disconnect: () => {},
    },
    emit: (frame: FeedFrame) => listener?.onFrame(frame),
  }
}

/** Mirrors `Workers.test.tsx`'s harness: a fake container behind the same
 *  `QueryClientProvider` + `ContainerProvider` pair every view renders inside,
 *  built as a partial container and cast -- the established pattern here. */
const renderHookWithContainer = <Props, Result>(
  hook: (props: Props) => Result,
  options: {
    initialProps: Props
    everywhere: WorkerRepository['everywhere']
    stream?: AppContainer['stream']
  },
) => {
  const parts: Partial<AppContainer> = {
    workers: { everywhere: options.everywhere, on: vi.fn() } as unknown as WorkerRepository,
    projects: { list: vi.fn().mockResolvedValue([]) } as unknown as AppContainer['projects'],
    stream: options.stream ?? fakeStream(),
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
 * So both states poll, at two rates. Open is fast because a reader is watching
 * rows change; closed is slow because a collapsed dock draws a count and the
 * cost is paid by every idle tab. Closed used to poll not at all, and that is
 * the defect this pins: a launched agent stayed invisible in the topbar until
 * the page was reloaded.
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

  // Closed: slower than the open rate, so three open-intervals buy nothing...
  await vi.advanceTimersByTimeAsync(ROSTER_POLL_MS * 3)
  expect(everywhere).toHaveBeenCalledTimes(1)

  // ...but it does poll, which is the whole fix. Without it the count never
  // moves for a turn, whose start appends no frame.
  await vi.advanceTimersByTimeAsync(IDLE_ROSTER_POLL_MS)
  expect(everywhere).toHaveBeenCalledTimes(2)

  rerender({ open: true })
  const openedAfter = everywhere.mock.calls.length
  await vi.advanceTimersByTimeAsync(ROSTER_POLL_MS * 3)
  expect(everywhere.mock.calls.length).toBeGreaterThan(openedAfter + 1)

  vi.useRealTimers()
})

/** Every frame that can mean "something started working".
 *
 * A dispatch, a seeding run and an extraction are each announced when the work
 * *begins* (`DispatchQueue.start` and its two neighbours), and each produces a
 * `Worker` in the roster (`WorkerRoster.on`). Extraction was the one this hook
 * did not listen for -- so starting an extraction moved the count only when the
 * poll came round, or, before the poll existed at all, only on a reload.
 *
 * Asserted with the dock *closed*, because that is the state whose freshness
 * came entirely from frames, and with fake timers off so nothing here can pass
 * on the interval instead.
 */
it.each(['dispatch', 'seeding', 'extraction'] as const)(
  'refetches the roster when a %s frame says work started',
  async (kind) => {
    const everywhere = vi.fn().mockResolvedValue([])
    const driver = drivableStream()

    renderHookWithContainer(() => useRunningAgents(false), {
      initialProps: undefined,
      everywhere,
      stream: driver.stream,
    })
    await vi.waitFor(() => expect(everywhere).toHaveBeenCalledTimes(1))

    driver.emit({ kind, projectId: 'p', run: {}, dispatch: {}, payload: {} } as FeedFrame)

    await vi.waitFor(() => expect(everywhere).toHaveBeenCalledTimes(2))
  },
)
