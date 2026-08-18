/** `DispatchRequested`, recorded off `useDispatchTopic`'s own `onSuccess` --
 *  see `use-extraction-queue.test.tsx` for why the provider is substituted
 *  rather than an injected dependency.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { InteractionLogContext } from '@app/interaction-log-provider.tsx'
import type { TopicRepository } from '@application/ports/repositories.ts'
import { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import { useDispatchTopic } from './use-dispatch.ts'

const project = ProjectId('11111111-1111-4111-8111-111111111111')

const fakeTopics = (over: Partial<TopicRepository>): TopicRepository =>
  ({ ...over }) as TopicRepository

const wrapperFor = (topics: TopicRepository, client: QueryClient, record: () => void) => {
  const container = { topics } as unknown as AppContainer
  return ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>
        <InteractionLogContext.Provider value={{ record } as never}>
          {children}
        </InteractionLogContext.Provider>
      </QueryClientProvider>
    </ContainerProvider>
  )
}

describe('useDispatchTopic', () => {
  it('records DispatchRequested with the topic and the action pressed', async () => {
    const record = vi.fn()
    const client = new QueryClient()
    const dispatch = vi.fn().mockResolvedValue({})
    const topics = fakeTopics({ dispatch })

    const { result } = renderHook(() => useDispatchTopic(project), {
      wrapper: wrapperFor(topics, client, record),
    })
    result.current.mutate({ topicId: TopicId('t1'), action: 'research' })

    await waitFor(() => {
      expect(record).toHaveBeenCalledWith('DispatchRequested', {
        topic_id: 't1',
        action: 'research',
      })
    })
  })
})
