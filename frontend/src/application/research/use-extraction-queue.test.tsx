/** Telemetry recorded off the extraction mutations' own `onSuccess`, per
 *  `interaction-log-provider.tsx`'s contract: a hook reads `useInteractionLog`
 *  directly rather than taking an emitter as a dependency, and a test with no
 *  provider in its tree gets the silent default -- these tests substitute
 *  `InteractionLogContext.Provider` to observe what the default swallows.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { InteractionLogContext } from '@app/interaction-log-provider.tsx'
import type { DocumentRepository } from '@application/ports/repositories.ts'
import { queryKeys } from '@application/queries/keys.ts'
import type { ExtractionQueueBoard } from '@domain/research/extraction-queue.ts'
import { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { useCancelExtraction, useExtractDocument } from './use-extraction-queue.ts'

const project = ProjectId('11111111-1111-4111-8111-111111111111')

const fakeDocuments = (over: Partial<DocumentRepository>): DocumentRepository =>
  ({ ...over }) as DocumentRepository

const wrapperFor = (documents: DocumentRepository, client: QueryClient, record: () => void) => {
  const container = { documents } as unknown as AppContainer
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

describe('useExtractDocument', () => {
  it('records ExtractionQueued with the source that was pressed', async () => {
    const record = vi.fn()
    const client = new QueryClient()
    const extract = vi.fn().mockResolvedValue(true)
    const documents = fakeDocuments({ extract })

    const { result } = renderHook(() => useExtractDocument(project), {
      wrapper: wrapperFor(documents, client, record),
    })
    result.current.mutate(SourceId('s1'))

    await waitFor(() => {
      expect(record).toHaveBeenCalledWith('ExtractionQueued', { source_id: 's1' })
    })
  })
})

describe('useCancelExtraction', () => {
  it('records ExtractionCancelled with the source that was running', async () => {
    const record = vi.fn()
    const client = new QueryClient()
    // Seeded before the mutation runs: onMutate reads this snapshot because
    // the invalidation that follows a successful cancel is exactly what
    // clears `running` from the cache.
    const board: ExtractionQueueBoard = {
      running: SourceId('running-one'),
      queued: [],
      finished: [],
    }
    client.setQueryData(queryKeys.extractionQueue(project), board)
    const cancelExtraction = vi.fn().mockResolvedValue(1)
    const documents = fakeDocuments({ cancelExtraction })

    const { result } = renderHook(() => useCancelExtraction(project), {
      wrapper: wrapperFor(documents, client, record),
    })
    result.current.mutate()

    await waitFor(() => {
      expect(record).toHaveBeenCalledWith('ExtractionCancelled', { source_id: 'running-one' })
    })
  })

  it('records nothing when nothing was running', async () => {
    const record = vi.fn()
    const client = new QueryClient()
    const board: ExtractionQueueBoard = { running: null, queued: [SourceId('q1')], finished: [] }
    client.setQueryData(queryKeys.extractionQueue(project), board)
    const cancelExtraction = vi.fn().mockResolvedValue(1)
    const documents = fakeDocuments({ cancelExtraction })

    const { result } = renderHook(() => useCancelExtraction(project), {
      wrapper: wrapperFor(documents, client, record),
    })
    result.current.mutate()

    await waitFor(() => {
      expect(cancelExtraction).toHaveBeenCalled()
    })
    expect(record).not.toHaveBeenCalledWith('ExtractionCancelled', expect.anything())
  })
})
