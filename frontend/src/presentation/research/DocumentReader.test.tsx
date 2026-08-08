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
  droppedReason: null,
  text: 'Ada Lovelace worked with Charles Babbage.',
  start: 0,
  end: 41,
  ...over,
})

const fakeDocuments = (read: DocumentRepository['read']): DocumentRepository => ({
  list: vi.fn(() => {
    throw new Error('DocumentReader should never call list()')
  }),
  read,
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

it('shows the title as a heading, falling back to the source id', async () => {
  const documents = fakeDocuments(
    vi.fn<DocumentRepository['read']>().mockResolvedValue(text({ title: null })),
  )

  renderWithContainer(<DocumentReader projectId={PROJECT} sourceId={SOURCE} />, { documents })

  expect(await screen.findByRole('heading', { name: 's1' })).toBeInTheDocument()
})

it('reports an error rather than an empty pane when the read fails', async () => {
  const documents = fakeDocuments(
    vi.fn<DocumentRepository['read']>().mockRejectedValue(new Error('boom')),
  )

  renderWithContainer(<DocumentReader projectId={PROJECT} sourceId={SOURCE} />, { documents })

  expect(await screen.findByText(/boom/)).toBeInTheDocument()
})
