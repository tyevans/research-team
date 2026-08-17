import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useAskAttempts } from './use-ask-attempts.ts'
import type { Container } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { ComponentId, ProjectId } from '@domain/shared/identifier.ts'

const projectId = ProjectId('p1')
const block = { kind: 'component', id: ComponentId('q1') } as ComponentBlock

const harness = (submitAskAttempt: Container['ask']['submitAskAttempt']) => {
  const container = { ask: { submitAskAttempt } } as unknown as Container
  return ({ children }: { children: React.ReactNode }) => (
    <ContainerProvider container={container}>{children}</ContainerProvider>
  )
}

describe('useAskAttempts', () => {
  it('posts an attempt against its own turn and renders the verdict', async () => {
    const submitAskAttempt = vi.fn().mockResolvedValue({
      correct: true,
      score: 1,
      feedback: [],
      rationale: null,
      correctOptions: [],
      blanks: [],
      progress: null,
    })

    const { result } = renderHook(() => useAskAttempts(projectId, 'conv-1', 2), {
      wrapper: harness(submitAskAttempt),
    })

    await act(() => result.current.submit(block, [0]))

    expect(submitAskAttempt).toHaveBeenCalledWith(projectId, 'conv-1', {
      position: 2,
      componentId: block.id,
      response: [0],
    })
    expect(result.current.stateFor(block).verdict?.correct).toBe(true)
  })

  it('is a different set of answers for a different turn', () => {
    // Two widgets in one conversation are two documents. Answers typed against
    // turn 2 must not appear against turn 3 -- the same rule the lesson hook
    // holds for a changed path, which is why the key is shared.
    const submitAskAttempt = vi.fn().mockReturnValue(new Promise(() => {}))
    const { result, rerender } = renderHook(
      ({ position }: { position: number }) => useAskAttempts(projectId, 'conv-1', position),
      { wrapper: harness(submitAskAttempt), initialProps: { position: 2 } },
    )

    act(() => result.current.update(block, { picked: [1] }))
    expect(result.current.stateFor(block).picked).toEqual([1])

    rerender({ position: 3 })
    expect(result.current.stateFor(block).picked).toEqual([])
  })

  it('does not offer a checklist save', () => {
    // Nothing on this path can persist a tick, and a control that silently
    // drops what it was given is worse than one that is not there.
    const submitAskAttempt = vi.fn()
    const { result } = renderHook(() => useAskAttempts(projectId, 'conv-1', 2), {
      wrapper: harness(submitAskAttempt),
    })

    expect(result.current.saveChecklist).toBeUndefined()
  })
})
