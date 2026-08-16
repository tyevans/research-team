import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream } from '@application/ports/event-stream.ts'
import type { DocumentRepository } from '@application/ports/repositories.ts'
import type { TextSummary } from '@domain/research/document.ts'
import { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { StreamProvider } from '../shell/StreamProvider.tsx'
import { DocumentEditForm } from './DocumentEditForm.tsx'

const project = ProjectId('11111111-1111-1111-1111-111111111111')

const doc = (over: Partial<TextSummary> = {}): TextSummary => ({
  sourceId: SourceId('s1'),
  kind: 'text',
  charCount: 100,
  derivedFrom: null,
  degradations: [],
  sha256: 'deadbeef',
  uri: null,
  title: 'A Paper',
  publishedAt: null,
  note: null,
  fetchedAt: null,
  droppedReason: null,
  extracted: false,
  ...over,
})

const fakeDocuments = (over: Partial<DocumentRepository> = {}): DocumentRepository => ({
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
  perceive: vi.fn(() => {
    throw new Error('perceive was not stubbed for this test')
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

const revise = vi.fn<DocumentRepository['revise']>().mockResolvedValue(doc({ title: 'Fixed' }))
const documents = fakeDocuments({ revise })

const stream: EventStream = {
  connect: () => {},
  disconnect: () => {},
}

const wrapper = ({ children }: { children: ReactNode }): ReactElement => {
  const container = { documents, stream } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <StreamProvider>
          <OverlayHost>{children}</OverlayHost>
        </StreamProvider>
      </ContainerProvider>
    </QueryClientProvider>
  )
}

afterEach(() => {
  revise.mockClear()
})

it('sends only what changed, and no text', async () => {
  // The client half of the design: the server reads the stored text back when
  // none arrives, so correcting a title does not round-trip the prose and
  // cannot send back a stale copy of it.
  const user = userEvent.setup()
  render(<DocumentEditForm projectId={project} document={doc()} onDone={vi.fn()} />, {
    wrapper,
  })

  await user.clear(screen.getByLabelText('Title'))
  await user.type(screen.getByLabelText('Title'), 'Fixed')
  await user.click(screen.getByRole('button', { name: 'Save' }))

  await waitFor(() => {
    expect(revise).toHaveBeenCalledWith(project, 's1', { title: 'Fixed' })
  })
})

it('shows the identifier and does not let it be edited', async () => {
  // Changing it would create a different document and orphan every citation
  // pointing at the old id.
  render(<DocumentEditForm projectId={project} document={doc()} onDone={vi.fn()} />, {
    wrapper,
  })

  expect(screen.getByText('s1')).toBeInTheDocument()
  expect(screen.queryByLabelText('Identifier')).not.toBeInTheDocument()
})
