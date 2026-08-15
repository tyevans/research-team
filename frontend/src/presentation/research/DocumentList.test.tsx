import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState, type ReactElement, type ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { useToasts } from '@application/notifications/toast-store.ts'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import type { DocumentRepository } from '@application/ports/repositories.ts'
import type { MediaSummary, TextSummary } from '@domain/research/document.ts'
import { emptyExtractionQueue } from '@domain/research/extraction-queue.ts'
import { EventIndex } from '@domain/session/event-index.ts'
import { ProjectId, SessionId, SourceId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { StreamProvider } from '../shell/StreamProvider.tsx'
import { FRAME_DEBOUNCE_MS } from '../shell/use-frame-refresh.ts'
import { DocumentList } from './DocumentList.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

/** `DocumentList` with the route's job done by `useState`.
 *
 * Which document is open belongs to the address bar now -- `CitationList`
 * writes `#/p/<id>/doc/<sourceId>` and that link was opening the tab with
 * nothing read, because the pane held the open document in its own state. The
 * two tests below are about the drawer rather than about routing, so they need
 * *something* to close the loop `ProjectView` closes with `navigate`; this is
 * the smallest honest stand-in. A test that rendered `DocumentList` bare would
 * now assert that clicking a row does nothing, which is true and is not what it
 * was written to say.
 */
const Routed = ({ initial = null }: { initial?: SourceId | null }) => {
  const [open, setOpen] = useState<SourceId | null>(initial)
  return <DocumentList projectId={PROJECT} open={open} onOpen={setOpen} />
}

/** A text row. `Partial<TextSummary>` rather than `Partial<SourceSummary>`:
 *  a partial of the union widens to a shape that is neither member -- one
 *  carrying `charCount` *and* an optional `mediaType` -- which is exactly what
 *  the union exists to make unrepresentable. */
const doc = (over: Partial<TextSummary> = {}): TextSummary => ({
  sourceId: SourceId('s1'),
  kind: 'text',
  charCount: 100,
  sha256: 'deadbeef',
  uri: null,
  title: null,
  publishedAt: null,
  note: null,
  fetchedAt: null,
  droppedReason: null,
  extracted: false,
  ...over,
})

/** A media row, built separately rather than as `doc({ kind: 'media' })` --
 *  see `doc` above for why a fixture over the union would be the wrong shape.
 *  A fixture that can build a row carrying both counts can hide a component
 *  reading the wrong one. */
const media = (over: Partial<MediaSummary> = {}): MediaSummary => ({
  sourceId: SourceId('m1'),
  kind: 'media',
  mediaType: 'video/mp4',
  byteCount: 12_500_000,
  sha256: 'deadbeef',
  uri: null,
  title: null,
  publishedAt: null,
  note: null,
  fetchedAt: null,
  droppedReason: null,
  extracted: false,
  ...over,
})

/** `DocumentList` calls `list` and `extractionQueue` on mount -- reading one
 *  document's text is `DocumentReader`'s job once a row is opened, and the
 *  three extraction writes only happen on a press.
 *
 * The queue answers empty by default so the tests that predate extraction read
 * exactly as they did: an empty board is what a project with nothing
 * extracting has, not a stand-in for one. */
const fakeDocuments = (
  list: DocumentRepository['list'],
  over: Partial<DocumentRepository> = {},
): DocumentRepository => ({
  list,
  read: vi.fn(() => {
    throw new Error('read was not stubbed for this test')
  }),
  extract: vi.fn<DocumentRepository['extract']>().mockResolvedValue(true),
  extractAll: vi.fn<DocumentRepository['extractAll']>().mockResolvedValue(0),
  extractionQueue: vi
    .fn<DocumentRepository['extractionQueue']>()
    .mockResolvedValue(emptyExtractionQueue),
  cancelExtraction: vi.fn<DocumentRepository['cancelExtraction']>().mockResolvedValue(0),
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
  // Not a `vi.fn` that throws, unlike its neighbours: the media pane calls
  // this while *rendering* rather than in an effect, so a throwing stub is an
  // exception during render and the whole drawer disappears instead of the
  // test reporting which call was unstubbed.
  contentUrl: (projectId, sourceId) => `/api/projects/${projectId}/sources/${sourceId}/content`,
  uploadMedia: vi.fn(() => {
    throw new Error('uploadMedia was not stubbed for this test')
  }),
  ...over,
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
    /** An extraction frame arrives undecoded — `decodeFrame` routes the raw
     *  payload on purpose — so this pushes the wire shape, not a domain
     *  object. A test that pushed a decoded frame would exercise a path the
     *  application does not have. */
    pushExtraction: (stage: string, sourceId = 's1', projectId: string = PROJECT) =>
      act(() => {
        listener?.onFrame({
          kind: 'extraction',
          payload: {
            type: 'Extraction',
            project_id: projectId,
            source_id: sourceId,
            stage,
            detail: '',
          },
        })
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
  // `data-*` rather than the class names this row used to carry. The dressing
  // is utilities now, and a test that asserted on a utility string would fail
  // on a colour change that broke nothing; the state is the thing this test is
  // about and the attribute is where the state lives.
  const row = droppedTitle.closest('[data-document-row]')
  expect(row).not.toBeNull()
  expect(row).toHaveAttribute('data-dropped', 'true')
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

  const row = (await screen.findByText('Ada Lovelace')).closest('[data-document-row]')
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

  renderWithContainer(<Routed />, { documents })

  await user.click(await screen.findByRole('button', { name: /ada lovelace/i }))

  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveAttribute('aria-modal', 'true')
  expect(within(dialog).getByText(/analytical engine/i)).toBeInTheDocument()
})

it('discards stale edit state when the open document changes under it', async () => {
  // Driven by `open` changing rather than a row click: `OverlayHost` marks
  // everything behind a modal drawer both `inert` and `aria-hidden` (the
  // second exists *because* jsdom does not enforce the first), so a row
  // click here would not reach the rail in this environment any more than it
  // would in a real one. `open` is still free to change from outside the DOM
  // that is `inert`-blocked -- exactly the address-bar case `useDocuments`'s
  // own comment describes for `CitationList` -- and that is enough to
  // reproduce the bug: nothing in `DocumentManagePane` or `DocumentEditForm`
  // resets its own `useState` on a prop change, so without `key={reading}` on
  // `DocumentManagePane` the edit form keeps showing "Fixed" -- s1's edited
  // title -- after `document` underneath it has already become s2's summary.
  const documents = fakeDocuments(
    vi
      .fn<DocumentRepository['list']>()
      .mockResolvedValue([
        doc({ sourceId: SourceId('s1'), title: 'Ada Lovelace' }),
        doc({ sourceId: SourceId('s2'), title: 'Grace Hopper' }),
      ]),
  )
  documents.read = vi.fn<DocumentRepository['read']>().mockImplementation((_projectId, sourceId) =>
    Promise.resolve({
      sourceId,
      title: sourceId === 's1' ? 'Ada Lovelace' : 'Grace Hopper',
      text: sourceId === 's1' ? 'Notes on the Analytical Engine.' : 'Notes on the compiler.',
      droppedReason: null,
    } as Awaited<ReturnType<DocumentRepository['read']>>),
  )
  const user = userEvent.setup()

  const { rerender } = renderWithContainer(
    <DocumentList projectId={PROJECT} open={SourceId('s1')} onOpen={() => {}} />,
    { documents },
  )

  await screen.findByRole('dialog')
  await user.click(await screen.findByRole('button', { name: 'Edit' }))

  await user.clear(screen.getByLabelText('Title'))
  await user.type(screen.getByLabelText('Title'), 'Fixed')
  expect(screen.getByLabelText('Title')).toHaveValue('Fixed')

  rerender(<DocumentList projectId={PROJECT} open={SourceId('s2')} onOpen={() => {}} />)

  // The reader for the new document is what should be on screen -- either
  // showing s2's text directly, or (if a reader chose Edit again) an edit
  // form pre-filled from s2, but never s1's half-typed correction.
  expect(await screen.findByText(/compiler/i)).toBeInTheDocument()
  expect(screen.queryByDisplayValue('Fixed')).not.toBeInTheDocument()
})

it('opens the document the route names, with no click at all', async () => {
  // The regression `CitationList` has been shipping into: `#/p/<id>/doc/<id>`
  // parsed, reached MATERIAL and opened the Documents tab, and the id was then
  // dropped because `DocumentList` took `projectId` alone and held the open
  // document in `useState`. A reader following a citation got an unfiltered
  // corpus and had to find the source by hand.
  //
  // Reverting the `open` prop -- back to `useState` inside `useDocuments` --
  // fails here, because nothing in this test ever clicks a row.
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

  renderWithContainer(<Routed initial={SourceId('s1')} />, { documents })

  const dialog = await screen.findByRole('dialog')
  // `findByText`, not `getByText`, and the difference is the whole reason this
  // test failed in CI while its clicking sibling above passed. The drawer's
  // *header* comes from the list, so the dialog exists as soon as the route is
  // read; the body is a second request (`documents.read`) and is still
  // `loading document…` at that moment. The sibling gets away with `getByText`
  // because `user.click` flushes the microtask queue on its way out, which is a
  // property of user-event rather than of the component — so a test with no
  // click has to wait for the read itself.
  expect(await within(dialog).findByText(/analytical engine/i)).toBeInTheDocument()
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

  renderWithContainer(<Routed />, { documents })

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

it('queues the document whose extract control was pressed', async () => {
  // Held in a local rather than read back off the repository: `expect(obj.fn)`
  // trips `@typescript-eslint/unbound-method`, which is a lint gate here.
  const extract = vi.fn<DocumentRepository['extract']>().mockResolvedValue(true)
  const documents = fakeDocuments(
    vi
      .fn<DocumentRepository['list']>()
      .mockResolvedValue([doc({ sourceId: SourceId('s1'), title: 'Ada Lovelace' })]),
    { extract },
  )
  const user = userEvent.setup()

  renderWithContainer(<DocumentList projectId={PROJECT} />, { documents })
  await screen.findByText('Ada Lovelace')

  await user.click(screen.getByRole('button', { name: 'Extract' }))

  expect(extract).toHaveBeenCalledWith(PROJECT, 's1')
  await waitFor(() =>
    expect(useToasts.getState().toasts.at(-1)?.message).toBe('Queued for extraction'),
  )
})

/** The one the server shaped its 202 around. `queued: false` means the queue
 *  already holds this document -- not an error, and not a start -- and a
 *  client that toasted "queued" either way would be claiming it started
 *  something it did not. Reverting the `onSuccess` to a single unconditional
 *  message fails here. */
it('does not claim to have started an extraction the queue already held', async () => {
  const documents = fakeDocuments(
    vi
      .fn<DocumentRepository['list']>()
      .mockResolvedValue([doc({ sourceId: SourceId('s1'), title: 'Ada Lovelace' })]),
    { extract: vi.fn<DocumentRepository['extract']>().mockResolvedValue(false) },
  )
  const user = userEvent.setup()

  renderWithContainer(<DocumentList projectId={PROJECT} />, { documents })
  await screen.findByText('Ada Lovelace')

  await user.click(screen.getByRole('button', { name: 'Extract' }))

  await waitFor(() =>
    expect(useToasts.getState().toasts.at(-1)?.message).toBe('Already queued for extraction'),
  )
})

/** The count comes back from the press, not from the corpus this side counted.
 *  The server recomputes the set at press time and refuses what the queue
 *  already holds, so the two differ exactly when a previous press is still
 *  draining -- reporting the local estimate would overstate it there. */
it('reports how many extract-all actually took on', async () => {
  const extractAll = vi.fn<DocumentRepository['extractAll']>().mockResolvedValue(1)
  const documents = fakeDocuments(
    vi
      .fn<DocumentRepository['list']>()
      .mockResolvedValue([
        doc({ sourceId: SourceId('s1'), title: 'Ada Lovelace' }),
        doc({ sourceId: SourceId('s2'), title: 'Grace Hopper' }),
      ]),
    { extractAll },
  )
  const user = userEvent.setup()

  renderWithContainer(<DocumentList projectId={PROJECT} />, { documents })
  await screen.findByText('Ada Lovelace')

  // Two unextracted rows, and the press answers 1: the number on the button is
  // this side's estimate, the number in the toast is what happened.
  await user.click(screen.getByRole('button', { name: 'Extract all (2)' }))

  expect(extractAll).toHaveBeenCalledWith(PROJECT)
  await waitFor(() =>
    expect(useToasts.getState().toasts.at(-1)?.message).toBe('Queued 1 document for extraction'),
  )
})

/** The live half, and the design decision this slice turns on.
 *
 * The extraction queue publishes no frames of its own, so the only
 * announcement a terminal extraction makes is the `Extraction` frame the
 * ingest emits — and that frame has to invalidate *both* the queue and the
 * corpus listing, because the row's `extracted` flag lives on the listing.
 * Without the second invalidation the row kept offering "Extract" on a
 * document that had just been extracted, until a reload.
 *
 * Reverting either invalidation fails here: the queue one leaves the row
 * saying "Extracting…", the documents one leaves it offering "Extract".
 */
it('flips a row to extracted when its extraction finishes, without a reload', async () => {
  const list = vi
    .fn<DocumentRepository['list']>()
    .mockResolvedValueOnce([doc({ sourceId: SourceId('s1'), title: 'Ada Lovelace' })])
    .mockResolvedValue([doc({ sourceId: SourceId('s1'), title: 'Ada Lovelace', extracted: true })])
  const extractionQueue = vi
    .fn<DocumentRepository['extractionQueue']>()
    .mockResolvedValueOnce({ running: SourceId('s1'), queued: [], finished: [] })
    .mockResolvedValue(emptyExtractionQueue)
  const feed = fakeStream()

  renderWithContainer(
    <DocumentList projectId={PROJECT} />,
    { documents: fakeDocuments(list, { extractionQueue }) },
    feed.stream,
  )
  expect(await screen.findByText('Extracting…')).toBeInTheDocument()

  feed.pushExtraction('consolidated')

  expect(await screen.findByText('Extracted', {}, { timeout: 2_000 })).toBeInTheDocument()
})

/** Only terminal stages, and only this project's.
 *
 * A refresh per progress note would be a read for a board that has not moved:
 * the running document is still the running document until it stops being one.
 *
 * Stated plainly: this asserts an absence and so passes with the extraction
 * subscription removed entirely. It pins the *scope* of the refresh, not the
 * refresh -- the test above it is the red one. */
it('ignores a mid-flight extraction note and another project’s frames', async () => {
  const list = vi.fn<DocumentRepository['list']>().mockResolvedValue([doc()])
  const extractionQueue = vi
    .fn<DocumentRepository['extractionQueue']>()
    .mockResolvedValue(emptyExtractionQueue)
  const feed = fakeStream()

  renderWithContainer(
    <DocumentList projectId={PROJECT} />,
    { documents: fakeDocuments(list, { extractionQueue }) },
    feed.stream,
  )
  await screen.findByText('s1')
  expect(extractionQueue).toHaveBeenCalledTimes(1)

  feed.pushExtraction('extracting')
  feed.pushExtraction('consolidating')
  feed.pushExtraction('consolidated', 's1', '99999999-9999-9999-9999-999999999999')

  await new Promise((resolve) => setTimeout(resolve, FRAME_DEBOUNCE_MS * 2))
  expect(extractionQueue).toHaveBeenCalledTimes(1)
  expect(list).toHaveBeenCalledTimes(1)
})

it('shows a media row by its type and size, not a character count', async () => {
  // A media row rendered through the text path shows "0 characters" -- or, if
  // the field is simply absent, "undefined chars" -- which reads as an empty
  // document rather than as a video. The failure this asserts against is a
  // plausible-looking row, not a crash, which is why it names the size and the
  // mimetype rather than merely checking that the row rendered at all.
  const documents = fakeDocuments(
    vi
      .fn<DocumentRepository['list']>()
      .mockResolvedValue([media({ title: 'The keynote', byteCount: 12_500_000 })]),
  )

  renderWithContainer(<DocumentList projectId={PROJECT} />, { documents })

  const row = (await screen.findByText('The keynote')).closest('[data-document-row]')
  expect(row).not.toBeNull()
  expect(within(row as HTMLElement).getByText(/12\.5 MB/)).toBeInTheDocument()
  expect(within(row as HTMLElement).getByText(/video\/mp4/)).toBeInTheDocument()
  expect(within(row as HTMLElement).queryByText(/chars/)).not.toBeInTheDocument()
})

it('does not offer extraction on a media row, which the server would refuse', async () => {
  // `_unextracted` on the server counts `kind == "text"` rows only, so a media
  // row offering "Extract" would offer an action extract-all has already
  // decided against -- and the header's "Extract all (N)" would promise a
  // document it cannot take on. Both halves are asserted: the missing control,
  // and the count that does not include it.
  const documents = fakeDocuments(
    vi
      .fn<DocumentRepository['list']>()
      .mockResolvedValue([doc({ title: 'A paper' }), media({ title: 'The keynote' })]),
  )

  renderWithContainer(<DocumentList projectId={PROJECT} />, { documents })

  const row = (await screen.findByText('The keynote')).closest('[data-document-row]')
  expect(within(row as HTMLElement).queryByRole('button', { name: 'Extract' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Extract all (1)' })).toBeInTheDocument()
})

it('offers drop on a media row exactly as on a text one', async () => {
  // One `source_id` namespace means one set of actions. A media row missing
  // them would make a dropped video unrecoverable through the console.
  const documents = fakeDocuments(
    vi.fn<DocumentRepository['list']>().mockResolvedValue([media({ title: 'The keynote' })]),
  )

  renderWithContainer(<Routed initial={SourceId('m1')} />, { documents })

  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByRole('button', { name: 'Drop' })).toBeInTheDocument()
  expect(within(dialog).getByRole('button', { name: 'Edit' })).toBeInTheDocument()
})

it('offers restore on a dropped media row', async () => {
  const documents = fakeDocuments(
    vi
      .fn<DocumentRepository['list']>()
      .mockResolvedValue([media({ title: 'The keynote', droppedReason: 'wrong recording' })]),
  )

  renderWithContainer(<Routed initial={SourceId('m1')} />, { documents })

  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByRole('button', { name: 'Restore' })).toBeInTheDocument()
})
