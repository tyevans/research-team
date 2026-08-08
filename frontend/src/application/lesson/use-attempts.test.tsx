import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'

import { useAttempts } from './use-attempts.ts'
import type { Container } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { ItemProgress } from '@domain/lesson/attempt.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import { ComponentId, SessionId } from '@domain/shared/identifier.ts'

const session = SessionId('s1')
const block = { kind: 'component', id: ComponentId('q1') } as ComponentBlock

const stored = (over: Partial<ItemProgress> = {}): ItemProgress => ({
  attempts: 3,
  correct: true,
  bestScore: 1,
  lastScore: 1,
  checked: [],
  ...over,
})

/** A lesson port whose `progress` call this test controls the timing of, because
 *  the ordering between "the learner started answering" and "their history
 *  arrived" is the whole point of these cases. */
const harness = (progress: () => Promise<ReadonlyMap<ComponentId, ItemProgress>>) => {
  const container = { lessons: { progress } } as unknown as Container
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>{children}</ContainerProvider>
    </QueryClientProvider>
  )
  return wrapper
}

const never = () => new Promise<ReadonlyMap<ComponentId, ItemProgress>>(() => {})

describe('useAttempts', () => {
  it('folds the learner’s stored history in', async () => {
    const { result } = renderHook(
      () => useAttempts(session, FilePath.of('/a.md'), ScrubPoint.head()),
      { wrapper: harness(() => Promise.resolve(new Map([[ComponentId('q1'), stored()]]))) },
    )

    await waitFor(() => expect(result.current.stateFor(block).attempts).toBe(3))
    expect(result.current.stateFor(block).previouslyCorrect).toBe(true)
  })

  it('does not overwrite an answer in progress when the history lands late', async () => {
    // The ordering that used to be wrong. `progress` is fetched, so it can
    // resolve after the learner has already picked an option; folding it in at
    // that moment discarded what they had just done.
    let release: (value: ReadonlyMap<ComponentId, ItemProgress>) => void = () => {}
    const late = new Promise<ReadonlyMap<ComponentId, ItemProgress>>((resolve) => {
      release = resolve
    })

    const { result } = renderHook(
      () => useAttempts(session, FilePath.of('/a.md'), ScrubPoint.head()),
      { wrapper: harness(() => late) },
    )

    act(() => result.current.update(block, { picked: [2] }))
    expect(result.current.stateFor(block).picked).toEqual([2])

    await act(async () => {
      release(new Map([[ComponentId('q1'), stored()]]))
      await late
    })

    expect(result.current.stateFor(block).picked).toEqual([2])
  })

  it('starts a different document blank, on the render that changes documents', () => {
    // Not one render later. The effect this replaced painted the previous
    // file's answers against the new file first, and only then cleared them.
    const { result, rerender } = renderHook(
      ({ path }: { path: string }) => useAttempts(session, FilePath.of(path), ScrubPoint.head()),
      { wrapper: harness(never), initialProps: { path: '/a.md' } },
    )

    act(() => result.current.update(block, { picked: [1] }))
    expect(result.current.stateFor(block).picked).toEqual([1])

    rerender({ path: '/b.md' })
    expect(result.current.stateFor(block).picked).toEqual([])
  })

  it('does not resurrect the first document’s answers on returning to it', () => {
    // Carrying a key means the stale entry is ignored, not archived — going
    // back must not restore answers the learner has been told are gone.
    const { result, rerender } = renderHook(
      ({ path }: { path: string }) => useAttempts(session, FilePath.of(path), ScrubPoint.head()),
      { wrapper: harness(never), initialProps: { path: '/a.md' } },
    )

    act(() => result.current.update(block, { picked: [1] }))
    rerender({ path: '/b.md' })
    rerender({ path: '/a.md' })

    expect(result.current.stateFor(block).picked).toEqual([])
  })

  it('keeps an edit to a component the learner already has history for', async () => {
    const { result } = renderHook(
      () => useAttempts(session, FilePath.of('/a.md'), ScrubPoint.head()),
      {
        wrapper: harness(() =>
          Promise.resolve(new Map([[ComponentId('q1'), stored({ checked: [0] })]])),
        ),
      },
    )

    await waitFor(() => expect(result.current.stateFor(block).attempts).toBe(3))
    act(() => result.current.update(block, { flipped: true }))

    // The edit is seeded from the stored state, so the history survives it.
    const state = result.current.stateFor(block)
    expect(state.flipped).toBe(true)
    expect(state.attempts).toBe(3)
    expect(state.ticked[0]).toBe(true)
  })
})
