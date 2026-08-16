import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { DocumentRepository } from '@application/ports/repositories.ts'
import { queryKeys } from '@application/queries/keys.ts'
import type { SourceSummary } from '@domain/research/document.ts'
import { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import {
  useCreateDocument,
  useDropDocument,
  useReviseDocument,
  useRestoreDocument,
} from './use-document-writes.ts'

const project = ProjectId('11111111-1111-4111-8111-111111111111')

const row: SourceSummary = {
  sourceId: SourceId('s1'),
  kind: 'text',
  charCount: 0,
  derivedFrom: null,
  degradations: [],
  sha256: '',
  uri: null,
  title: null,
  publishedAt: null,
  note: null,
  fetchedAt: null,
  droppedReason: null,
  extracted: false,
}

/** Only the method under test is stubbed to succeed -- the other three throw
 *  if called, so a test that invalidates the wrong query still fails loudly
 *  rather than passing because a fake elsewhere happened to resolve. */
const fakeDocuments = (over: Partial<DocumentRepository>): DocumentRepository => ({
  list: vi.fn(() => {
    throw new Error('list was not stubbed for this test')
  }),
  read: vi.fn(() => {
    throw new Error('read was not stubbed for this test')
  }),
  extract: vi.fn(() => {
    throw new Error('extract was not stubbed for this test')
  }),
  extractAll: vi.fn(() => {
    throw new Error('extractAll was not stubbed for this test')
  }),
  extractionQueue: vi.fn(() => {
    throw new Error('extractionQueue was not stubbed for this test')
  }),
  cancelExtraction: vi.fn(() => {
    throw new Error('cancelExtraction was not stubbed for this test')
  }),
  create: vi.fn(() => {
    throw new Error('create was not stubbed for this test')
  }),
  revise: vi.fn(() => {
    throw new Error('revise was not stubbed for this test')
  }),
  drop: vi.fn(() => {
    throw new Error('drop was not stubbed for this test')
  }),
  restore: vi.fn(() => {
    throw new Error('restore was not stubbed for this test')
  }),
  contentUrl: (projectId, sourceId) => `/api/projects/${projectId}/sources/${sourceId}/content`,
  uploadMedia: vi.fn(() => {
    throw new Error('uploadMedia was not stubbed for this test')
  }),
  ...over,
})

const wrapperFor = (documents: DocumentRepository, client: QueryClient) => {
  const container = { documents } as unknown as AppContainer
  return ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ContainerProvider>
  )
}

describe('useCreateDocument', () => {
  it('invalidates the listing only', async () => {
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const create = vi.fn().mockResolvedValue(row)
    const documents = fakeDocuments({ create })

    const { result } = renderHook(() => useCreateDocument(project), {
      wrapper: wrapperFor(documents, client),
    })
    result.current.mutate({ sourceId: 's1', text: 'hello' })

    await waitFor(() => {
      expect(create).toHaveBeenCalledWith(project, { sourceId: 's1', text: 'hello' })
    })
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.documents(project) })
    })
    // No reader to leave stale: a create names a document nothing has opened
    // yet, so a `document` invalidation would be a no-op query key and the
    // extra call would say nothing true about what changed.
    expect(invalidate).toHaveBeenCalledTimes(1)
  })
})

describe('useReviseDocument', () => {
  it('invalidates both the listing and the open document', async () => {
    // Two keys, not one. The listing carries the title and the reader carries
    // the text, and an edit can move either -- a reader left on the old key
    // would show the previous text under the new title.
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const revise = vi.fn().mockResolvedValue(row)
    const documents = fakeDocuments({ revise })

    const { result } = renderHook(() => useReviseDocument(project), {
      wrapper: wrapperFor(documents, client),
    })
    result.current.mutate({ sourceId: SourceId('s1'), edit: { title: 'Fixed' } })

    await waitFor(() => {
      expect(revise).toHaveBeenCalledWith(project, 's1', { title: 'Fixed' })
    })
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.documents(project) })
    })
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: queryKeys.document(project, SourceId('s1')),
      })
    })
  })
})

describe('useDropDocument', () => {
  it('invalidates the listing only', async () => {
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const drop = vi.fn().mockResolvedValue(row)
    const documents = fakeDocuments({ drop })

    const { result } = renderHook(() => useDropDocument(project), {
      wrapper: wrapperFor(documents, client),
    })
    result.current.mutate({ sourceId: SourceId('s1'), reason: 'superseded' })

    await waitFor(() => {
      expect(drop).toHaveBeenCalledWith(project, 's1', 'superseded')
    })
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.documents(project) })
    })
    // A drop changes only the record, not the text a reader would be showing,
    // so there is no stale document key to correct.
    expect(invalidate).toHaveBeenCalledTimes(1)
  })
})

describe('useRestoreDocument', () => {
  it('invalidates both the listing and the open document', async () => {
    // A restore re-stores the text, exactly like `revise` -- see that
    // describe block above for why one key is not enough.
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const restore = vi.fn().mockResolvedValue(row)
    const documents = fakeDocuments({ restore })

    const { result } = renderHook(() => useRestoreDocument(project), {
      wrapper: wrapperFor(documents, client),
    })
    result.current.mutate(SourceId('s1'))

    await waitFor(() => {
      expect(restore).toHaveBeenCalledWith(project, 's1')
    })
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.documents(project) })
    })
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: queryKeys.document(project, SourceId('s1')),
      })
    })
  })
})
