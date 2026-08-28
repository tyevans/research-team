import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { FeedFrame } from '@application/ports/event-stream.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { StreamProvider } from '../shell/StreamProvider.tsx'
import { FRAME_DEBOUNCE_MS } from '../shell/use-frame-refresh.ts'
import { useProject } from './use-project.ts'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')
const OTHER = ProjectId('99999999-9999-4999-8999-999999999999')
const HOLDER = SessionId('22222222-2222-4222-8222-222222222222')

const detail = (over: Record<string, unknown> = {}) => ({
  id: PROJECT,
  name: 'atlas',
  activeSessionId: null,
  tipAtEvent: 0,
  ...over,
})

/** The real `StreamProvider`, fed by a stub connection whose `onFrame` this
 *  keeps a handle on -- so a test can push a frame the way the server would
 *  rather than reaching into the hook's subscription. */
let push: (frame: FeedFrame) => void = () => {}

const wrapperFor = (project: () => Promise<unknown>, client: QueryClient) => {
  const container = {
    projects: { project },
    stream: {
      connect: ({ onFrame }: { onFrame: (frame: FeedFrame) => void }) => {
        push = onFrame
      },
      disconnect: vi.fn(),
    },
  } as unknown as AppContainer

  return ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>
        <StreamProvider>{children}</StreamProvider>
      </QueryClientProvider>
    </ContainerProvider>
  )
}

const clientWithoutRetries = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false } } })

describe('useProject', () => {
  beforeEach(() => {
    push = () => {}
  })

  it('exposes the project name and the holding session once the read settles', async () => {
    const project = vi.fn().mockResolvedValue(detail({ activeSessionId: HOLDER }))

    const { result } = renderHook(() => useProject(PROJECT), {
      wrapper: wrapperFor(project, clientWithoutRetries()),
    })

    // The pre-settled state is asserted first because it is the one that ships
    // on every page load: a breadcrumb that read `undefined` here would print
    // the word rather than fall back to a short id.
    expect(result.current.projectName).toBeNull()
    expect(result.current.holdingSessionId).toBeNull()

    await waitFor(() => {
      expect(result.current.projectName).toBe('atlas')
    })
    expect(result.current.holdingSessionId).toBe(HOLDER)
    expect(project).toHaveBeenCalledWith(PROJECT)
  })

  it('re-reads the project when a project frame names it', async () => {
    // The subscription carried across from `useCourseRefresh`, and the reason
    // it is not workflow machinery: `ProjectSessionJoined` is what moves the
    // holding-session link, and without this the header kept pointing at
    // nobody until a reload. Reverting the `useProjectRefresh` call fails this
    // test with one call rather than two.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const project = vi
      .fn()
      .mockResolvedValueOnce(detail())
      .mockResolvedValue(detail({ activeSessionId: HOLDER }))

    const { result } = renderHook(() => useProject(PROJECT), {
      wrapper: wrapperFor(project, clientWithoutRetries()),
    })
    await waitFor(() => {
      expect(result.current.projectName).toBe('atlas')
    })

    act(() => {
      push({ kind: 'project', projectId: PROJECT, change: 'ProjectSessionJoined', decision: null })
      vi.advanceTimersByTime(FRAME_DEBOUNCE_MS)
    })

    await waitFor(() => {
      expect(result.current.holdingSessionId).toBe(HOLDER)
    })
    vi.useRealTimers()
  })

  it('ignores a project frame for a different project', async () => {
    // Scoping is the whole reason the frame carries a project id. Without the
    // `projectId` half of the predicate every open project page refetches on
    // every other project's frame, which is invisible in a browser and is a
    // fan-out on the server.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const project = vi.fn().mockResolvedValue(detail())

    const { result } = renderHook(() => useProject(PROJECT), {
      wrapper: wrapperFor(project, clientWithoutRetries()),
    })
    await waitFor(() => {
      expect(result.current.projectName).toBe('atlas')
    })

    act(() => {
      push({ kind: 'project', projectId: OTHER, change: 'ProjectSessionJoined', decision: null })
      vi.advanceTimersByTime(FRAME_DEBOUNCE_MS)
    })

    expect(project).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })
})
