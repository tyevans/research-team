import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
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
import { DocumentManagePane } from './DocumentManagePane.tsx'

const project = ProjectId('11111111-1111-1111-1111-111111111111')

const doc = (over: Partial<TextSummary> = {}): TextSummary => ({
  sourceId: SourceId('s1'),
  kind: 'text',
  charCount: 100,
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

/** Copied from `DocumentUpload.test.tsx` -- there is no MSW here, the port is
 *  what gets faked, and every method throws until a test stubs it. */
const fakeDocuments = (over: Partial<DocumentRepository> = {}): DocumentRepository => ({
  list: vi.fn(() => {
    throw new Error('list was not stubbed for this test')
  }),
  read: vi.fn<DocumentRepository['read']>().mockResolvedValue({
    ...doc(),
    text: 'the body',
    start: 0,
    end: 8,
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

const drop = vi
  .fn<DocumentRepository['drop']>()
  .mockResolvedValue(doc({ droppedReason: 'off topic' }))
const documents = fakeDocuments({ drop })

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
  drop.mockClear()
})

const props = (over: Partial<TextSummary> = {}) => ({
  projectId: project,
  sourceId: SourceId('s1'),
  document: doc(over),
})

it('offers Drop for a live document and Restore for a dropped one', async () => {
  render(<DocumentManagePane {...props({ droppedReason: null })} />, { wrapper })
  expect(await screen.findByRole('button', { name: 'Drop' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Restore' })).not.toBeInTheDocument()

  cleanup()
  render(<DocumentManagePane {...props({ droppedReason: 'off topic' })} />, { wrapper })
  expect(await screen.findByRole('button', { name: 'Restore' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Drop' })).not.toBeInTheDocument()
})

it('will not drop without a reason', async () => {
  // The aggregate refuses a blank reason and would answer 409. Refused here
  // too, so the person is told by the field rather than by a toast.
  const user = userEvent.setup()
  render(<DocumentManagePane {...props({ droppedReason: null })} />, { wrapper })

  await user.click(await screen.findByRole('button', { name: 'Drop' }))
  await user.click(screen.getByRole('button', { name: 'Drop document' }))

  expect(drop).not.toHaveBeenCalled()
})

it('drops with the reason typed', async () => {
  const user = userEvent.setup()
  render(<DocumentManagePane {...props({ droppedReason: null })} />, { wrapper })

  await user.click(await screen.findByRole('button', { name: 'Drop' }))
  await user.type(screen.getByLabelText('Reason'), 'off topic')
  await user.click(screen.getByRole('button', { name: 'Drop document' }))

  await waitFor(() => {
    expect(drop).toHaveBeenCalledWith(project, 's1', 'off topic')
  })
})
