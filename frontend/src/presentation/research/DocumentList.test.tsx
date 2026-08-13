import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import type { DocumentRepository } from '@application/ports/repositories.ts'
import type { DocumentSummary } from '@domain/research/document.ts'
import { EventIndex } from '@domain/session/event-index.ts'
import { ProjectId, SessionId, SourceId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { StreamProvider } from '../shell/StreamProvider.tsx'
import { FRAME_DEBOUNCE_MS } from '../shell/use-frame-refresh.ts'
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

/** Mirrors `TopicList.test.tsx`'s fake stream, so a live-update assertion
 *  drives the real `StreamProvider` fan-out rather than calling a prop. */
const fakeStream = () => {
  let listener: EventStreamListener | null = null
  const stream: EventStream = {
    connect: (received) => {
      listener = received
    },
    disconnect: () => {
      listener = null
    },
  }
  return {
    stream,
    pushCorpus: (projectId: string = PROJECT, change = 'CorpusDocumentStored') =>
      act(() => {
        listener?.onFrame({ kind: 'corpus', projectId, change })
      }),
    pushGraph: () =>
      act(() => {
        listener?.onFrame({ kind: 'graph', projectId: PROJECT, change: 'DocumentExtracted' })
      }),
    pushLog: () =>
      act(() => {
        listener?.onFrame({
          kind: 'log',
          sessionId: SessionId('cccccccc-cccc-cccc-cccc-cccccccccccc'),
          entry: {
            index: EventIndex(1),
            type: 'FileWritten',
            occurredAt: '2026-01-01T00:00:00Z',
            summary: '/a.md',
            path: '/a.md',
            turnIndex: null,
            isError: false,
            cancelled: null,
          },
        })
      }),
  }
}

/** The `StreamProvider` is not decoration: `DocumentList` subscribes to the
 *  feed, and a harness without one would exercise a component the application
 *  never renders. */
const renderWithContainer = (
  ui: ReactElement,
  parts: Partial<AppContainer>,
  stream: EventStream = fakeStream().stream,
) => {
  const container = { stream, ...parts } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  // An `OverlayHost`, because this page opens a `Drawer`/`Confirm`, both of
  // which are `Overlay`s and render nothing without one. In the application
  // this comes from `Shell`.
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <StreamProvider>
          <OverlayHost>{children}</OverlayHost>
        </StreamProvider>
      </ContainerProvider>
    </QueryClientProvider>
  )
  return render(ui, { wrapper })
}

it('renders every document’s label', async () => {
  const documents = fakeDocuments(
    vi
      .fn<DocumentRepository['list']>()
      .mockResolvedValue([
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

it('lets a row be as tall as its title instead of pinning it to one row height', async () => {
  // A fixed 52px row treated a wrapped title as if it took one line, so a
  // two-line title -- most of them, in a 340px rail -- drew over the row
  // beneath it. Rows are measured now, which needs three things from the DOM:
  // the index the virtualizer reads back to know what it measured, a transform
  // rather than a `top` offset (a measured row would otherwise be offset
  // twice), and no inline height overriding the content.
  //
  // The heights themselves are not asserted: jsdom has no layout, so every
  // measurement there is 0. This pins the shape that makes measuring work; the
  // drawing itself was checked in a browser.
  const documents = fakeDocuments(
    vi
      .fn<DocumentRepository['list']>()
      .mockResolvedValue([doc({ sourceId: SourceId('s1'), title: 'Ada Lovelace' })]),
  )

  renderWithContainer(<DocumentList projectId={PROJECT} />, { documents })

  const row = (await screen.findByText('Ada Lovelace')).closest('.document-row')
  expect(row).not.toBeNull()
  expect(row).toHaveAttribute('data-index', '0')
  expect((row as HTMLElement).style.transform).toBe('translateY(0px)')
  expect((row as HTMLElement).style.height).toBe('')
})

it('opens a document over the page rather than below the list', async () => {
  // The list sits in a 340px rail. Rendered inline, a document was a few words
  // per line under a list that had been pushed out of the way, so the reader
  // belongs in the same drawer the console already uses for reading something
  // without losing your place.
  const documents = fakeDocuments(
    vi
      .fn<DocumentRepository['list']>()
      .mockResolvedValue([doc({ sourceId: SourceId('s1'), title: 'Ada Lovelace' })]),
  )
  documents.read = vi.fn<DocumentRepository['read']>().mockResolvedValue({
    sourceId: SourceId('s1'),
    title: 'Ada Lovelace',
    text: 'Notes on the Analytical Engine.',
    droppedReason: null,
  } as Awaited<ReturnType<DocumentRepository['read']>>)
  const user = userEvent.setup()

  renderWithContainer(<DocumentList projectId={PROJECT} />, { documents })

  await user.click(await screen.findByRole('button', { name: /ada lovelace/i }))

  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveAttribute('aria-modal', 'true')
  expect(within(dialog).getByText(/analytical engine/i)).toBeInTheDocument()
})

it('closes the open document on Escape, leaving the list behind it', async () => {
  const documents = fakeDocuments(
    vi
      .fn<DocumentRepository['list']>()
      .mockResolvedValue([doc({ sourceId: SourceId('s1'), title: 'Ada Lovelace' })]),
  )
  documents.read = vi.fn<DocumentRepository['read']>().mockResolvedValue({
    sourceId: SourceId('s1'),
    title: 'Ada Lovelace',
    text: 'Notes on the Analytical Engine.',
    droppedReason: null,
  } as Awaited<ReturnType<DocumentRepository['read']>>)
  const user = userEvent.setup()

  renderWithContainer(<DocumentList projectId={PROJECT} />, { documents })

  await user.click(await screen.findByRole('button', { name: /ada lovelace/i }))
  await screen.findByRole('dialog')

  await user.keyboard('{Escape}')

  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByText('Ada Lovelace')).toBeInTheDocument()
})

it('says no documents exist yet rather than showing an empty box', async () => {
  const documents = fakeDocuments(vi.fn<DocumentRepository['list']>().mockResolvedValue([]))

  renderWithContainer(<DocumentList projectId={PROJECT} />, { documents })

  expect(await screen.findByText(/no documents/i)).toBeInTheDocument()
})

it('lists a document that arrived after the page did, without a reload', async () => {
  // The pane shipped subscribing to nothing at all, so a source the agent
  // stored mid-session sat invisible until the reader reloaded -- while the
  // turn that fetched it scrolled past in front of them. Reverting either half
  // of the fix (the `Corpus` frame, or this subscription) fails here.
  const list = vi
    .fn<DocumentRepository['list']>()
    .mockResolvedValueOnce([doc({ sourceId: SourceId('s1'), title: 'Ada Lovelace' })])
    .mockResolvedValue([
      doc({ sourceId: SourceId('s1'), title: 'Ada Lovelace' }),
      doc({ sourceId: SourceId('s2'), title: 'Grace Hopper' }),
    ])
  const feed = fakeStream()

  renderWithContainer(
    <DocumentList projectId={PROJECT} />,
    { documents: fakeDocuments(list) },
    feed.stream,
  )
  await screen.findByText('Ada Lovelace')

  feed.pushCorpus()

  expect(await screen.findByText('Grace Hopper', {}, { timeout: 2_000 })).toBeInTheDocument()
})

it('re-reads once for a burst of corpus frames, not once each', async () => {
  // An ingest of eight sources commits eight frames in a row. Without the
  // debounce that is eight identical list reads for one repaint.
  const list = vi.fn<DocumentRepository['list']>().mockResolvedValue([doc()])
  const feed = fakeStream()

  renderWithContainer(
    <DocumentList projectId={PROJECT} />,
    { documents: fakeDocuments(list) },
    feed.stream,
  )
  await screen.findByText('s1')
  expect(list).toHaveBeenCalledTimes(1)

  feed.pushCorpus()
  feed.pushCorpus()
  feed.pushCorpus()

  await waitFor(() => expect(list).toHaveBeenCalledTimes(2))
  await new Promise((resolve) => setTimeout(resolve, FRAME_DEBOUNCE_MS * 2))
  expect(list).toHaveBeenCalledTimes(2)
})

it('ignores graph and log frames, which change no document', async () => {
  // One ingest emits a corpus frame *and* a graph frame; refreshing on both
  // would double every read for no second answer. A log frame is ignored for
  // the reason `TopicList` ignores it: the tree already refetches on every
  // one, and this list doing the same would re-read the corpus on every token
  // of every turn.
  //
  // Stated plainly: this one passes with the subscription removed entirely.
  // It pins the *scope* of the fix, not the fix -- the two above are the red
  // ones.
  const list = vi.fn<DocumentRepository['list']>().mockResolvedValue([doc()])
  const feed = fakeStream()

  renderWithContainer(
    <DocumentList projectId={PROJECT} />,
    { documents: fakeDocuments(list) },
    feed.stream,
  )
  await screen.findByText('s1')

  feed.pushGraph()
  feed.pushLog()

  await new Promise((resolve) => setTimeout(resolve, FRAME_DEBOUNCE_MS * 2))
  expect(list).toHaveBeenCalledTimes(1)
})

it('ignores another project’s corpus frame', async () => {
  // Unlike a topic frame, this one names its project -- so a second project
  // ingesting in another tab costs this pane nothing rather than one wasted
  // read. That is the whole reason `corpus_change` carries a project id.
  //
  // Passes with the subscription removed, like the one above it: what it
  // pins is that the project test is applied, not that refreshing happens.
  const list = vi.fn<DocumentRepository['list']>().mockResolvedValue([doc()])
  const feed = fakeStream()

  renderWithContainer(
    <DocumentList projectId={PROJECT} />,
    { documents: fakeDocuments(list) },
    feed.stream,
  )
  await screen.findByText('s1')

  feed.pushCorpus('99999999-9999-9999-9999-999999999999')

  await new Promise((resolve) => setTimeout(resolve, FRAME_DEBOUNCE_MS * 2))
  expect(list).toHaveBeenCalledTimes(1)
})
