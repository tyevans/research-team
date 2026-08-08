import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { DocumentRepository } from '@application/ports/repositories.ts'
import type { DocumentSummary } from '@domain/research/document.ts'
import { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { DocumentList } from './DocumentList.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const doc = (over: Partial<DocumentSummary> = {}): DocumentSummary => ({
  sourceId: SourceId('s1'),
  charCount: 100,
  sha256: 'deadbeef',
  uri: null,
  title: null,
  publishedAt: null,
  note: null,
  droppedReason: null,
  ...over,
})

/** `DocumentList` only calls `list` -- reading one document's text is
 *  `DocumentReader`'s job once a row is opened. */
const fakeDocuments = (list: DocumentRepository['list']): DocumentRepository => ({
  list,
  read: vi.fn(() => {
    throw new Error('read was not stubbed for this test')
  }),
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

it('renders every document’s label', async () => {
  const documents = fakeDocuments(
    vi.fn<DocumentRepository['list']>().mockResolvedValue([
      doc({ sourceId: SourceId('s1'), title: 'Ada Lovelace' }),
      doc({ sourceId: SourceId('s2'), title: 'Grace Hopper' }),
    ]),
  )

  renderWithContainer(<DocumentList projectId={PROJECT} />, { documents })

  expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument()
  expect(screen.getByText('Grace Hopper')).toBeInTheDocument()
})

it('falls back to the source id when a document has no title', async () => {
  const documents = fakeDocuments(
    vi.fn<DocumentRepository['list']>().mockResolvedValue([doc({ sourceId: SourceId('raw-s7') })]),
  )

  renderWithContainer(<DocumentList projectId={PROJECT} />, { documents })

  expect(await screen.findByText('raw-s7')).toBeInTheDocument()
})

it('renders a dropped document’s reason and marks it, without hiding it', async () => {
  const documents = fakeDocuments(
    vi.fn<DocumentRepository['list']>().mockResolvedValue([
      doc({ sourceId: SourceId('s1'), title: 'Live one' }),
      doc({
        sourceId: SourceId('s2'),
        title: 'Superseded paper',
        droppedReason: 'superseded by a later edition',
      }),
    ]),
  )

  renderWithContainer(<DocumentList projectId={PROJECT} />, { documents })

  const droppedTitle = await screen.findByText('Superseded paper')
  expect(screen.getByText('Live one')).toBeInTheDocument()
  expect(screen.getByText(/superseded by a later edition/)).toBeInTheDocument()
  const row = droppedTitle.closest('.document-row')
  expect(row).not.toBeNull()
  expect(row!.className).toContain('document-dropped')
})

it('says no documents exist yet rather than showing an empty box', async () => {
  const documents = fakeDocuments(vi.fn<DocumentRepository['list']>().mockResolvedValue([]))

  renderWithContainer(<DocumentList projectId={PROJECT} />, { documents })

  expect(await screen.findByText(/no documents/i)).toBeInTheDocument()
})
