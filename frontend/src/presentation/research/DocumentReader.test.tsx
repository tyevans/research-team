import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { DocumentRepository } from '@application/ports/repositories.ts'
import type { DocumentText } from '@domain/research/document.ts'
import { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { DocumentReader } from './DocumentReader.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')
const SOURCE = SourceId('s1')

const text = (over: Partial<DocumentText> = {}): DocumentText => ({
  sourceId: SOURCE,
  charCount: 41,
  sha256: 'deadbeef',
  uri: null,
  title: 'Ada Lovelace',
  publishedAt: null,
  note: null,
  fetchedAt: null,
  droppedReason: null,
  extracted: false,
  text: 'Ada Lovelace worked with Charles Babbage.',
  start: 0,
  end: 41,
  ...over,
})

/** The reader neither queues nor reads the extraction queue, so every one of
 *  these throwing is the assertion: a reader that started calling them would
 *  fail here rather than quietly widening what this component does. */
const noExtraction = {
  extract: vi.fn(() => {
    throw new Error('DocumentReader should never queue an extraction')
  }),
  extractAll: vi.fn(() => {
    throw new Error('DocumentReader should never queue an extraction')
  }),
  extractionQueue: vi.fn(() => {
    throw new Error('DocumentReader should never read the extraction queue')
  }),
  cancelExtraction: vi.fn(() => {
    throw new Error('DocumentReader should never cancel an extraction')
  }),
  create: vi.fn(() => {
    throw new Error('DocumentReader should never create a document')
  }),
  revise: vi.fn(() => {
    throw new Error('DocumentReader should never revise a document')
  }),
  drop: vi.fn(() => {
    throw new Error('DocumentReader should never drop a document')
  }),
  restore: vi.fn(() => {
    throw new Error('DocumentReader should never restore a document')
  }),
} as unknown as Pick<
  DocumentRepository,
  | 'extract'
  | 'extractAll'
  | 'extractionQueue'
  | 'cancelExtraction'
  | 'create'
  | 'revise'
  | 'drop'
  | 'restore'
>

const fakeDocuments = (read: DocumentRepository['read']): DocumentRepository => ({
  list: vi.fn(() => {
    throw new Error('DocumentReader should never call list()')
  }),
  read,
  ...noExtraction,
})

const renderWithContainer = (ui: ReactElement, parts: Partial<AppContainer>) => {
  const container = parts as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>{children}</ContainerProvider>
    </QueryClientProvider>
  )
  return render(ui, { wrapper })
}

it('reads the document by id and shows its text', async () => {
  const read = vi.fn<DocumentRepository['read']>().mockResolvedValue(text())
  const documents = fakeDocuments(read)

  renderWithContainer(<DocumentReader projectId={PROJECT} sourceId={SOURCE} />, { documents })

  expect(await screen.findByText('Ada Lovelace worked with Charles Babbage.')).toBeInTheDocument()
  expect(read).toHaveBeenCalledWith(PROJECT, SOURCE, undefined)
})

it('leaves the title to the drawer around it rather than repeating it', async () => {
  // The drawer's header names the open document, and it names it from the list
  // row -- so it is correct while this component's fetch is still in flight,
  // where a heading here would appear a moment later underneath it. Two copies
  // of one title is chrome, not information.
  const documents = fakeDocuments(
    vi.fn<DocumentRepository['read']>().mockResolvedValue(text({ title: 'Ada Lovelace' })),
  )

  renderWithContainer(<DocumentReader projectId={PROJECT} sourceId={SOURCE} />, { documents })

  await screen.findByText('Ada Lovelace worked with Charles Babbage.')
  expect(screen.queryByRole('heading')).not.toBeInTheDocument()
})

it('reports an error rather than an empty pane when the read fails', async () => {
  const documents = fakeDocuments(
    vi.fn<DocumentRepository['read']>().mockRejectedValue(new Error('boom')),
  )

  renderWithContainer(<DocumentReader projectId={PROJECT} sourceId={SOURCE} />, { documents })

  expect(await screen.findByText(/boom/)).toBeInTheDocument()
})
