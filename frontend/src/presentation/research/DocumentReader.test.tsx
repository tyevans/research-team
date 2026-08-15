import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { DocumentRepository } from '@application/ports/repositories.ts'
import type { DocumentText, MediaSummary } from '@domain/research/document.ts'
import { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { DocumentReader } from './DocumentReader.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')
const SOURCE = SourceId('s1')
const MEDIA = SourceId('m1')

const media = (over: Partial<MediaSummary> = {}): MediaSummary => ({
  sourceId: MEDIA,
  kind: 'media',
  mediaType: 'video/mp4',
  byteCount: 12_500_000,
  sha256: 'deadbeef',
  uri: null,
  title: 'The keynote',
  publishedAt: null,
  note: null,
  fetchedAt: null,
  droppedReason: null,
  extracted: false,
  ...over,
})

const text = (over: Partial<DocumentText> = {}): DocumentText => ({
  sourceId: SOURCE,
  kind: 'text',
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
  // The real one is `${baseUrl}/api/...`; the fake keeps the path so the
  // assertions below read as the route they are pinning.
  contentUrl: (projectId, sourceId) => `/api/projects/${projectId}/sources/${sourceId}/content`,
  uploadMedia: vi.fn(() => {
    throw new Error('DocumentReader should never upload media')
  }),
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

  renderWithContainer(<DocumentReader projectId={PROJECT} sourceId={SOURCE} source={null} />, {
    documents,
  })

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

  renderWithContainer(<DocumentReader projectId={PROJECT} sourceId={SOURCE} source={null} />, {
    documents,
  })

  await screen.findByText('Ada Lovelace worked with Charles Babbage.')
  expect(screen.queryByRole('heading')).not.toBeInTheDocument()
})

it('renders a video source as a player against the content route', async () => {
  const documents = fakeDocuments(
    vi.fn(() => {
      throw new Error('read() must not be called for media')
    }),
  )

  renderWithContainer(<DocumentReader projectId={PROJECT} sourceId={MEDIA} source={media()} />, {
    documents,
  })

  const player = await screen.findByTestId('media-player')
  expect(player.tagName).toBe('VIDEO')
  expect(player).toHaveAttribute('src', `/api/projects/${PROJECT}/sources/m1/content`)
  // Browser-native controls, deliberately: there is no custom transport and no
  // thumbnail, so a player with `controls` off would be a video nobody can
  // pause. Asserted because it is a one-word regression.
  expect(player).toHaveAttribute('controls')
})

it('renders an image source as an image', async () => {
  const documents = fakeDocuments(
    vi.fn(() => {
      throw new Error('read() must not be called for media')
    }),
  )

  renderWithContainer(
    <DocumentReader
      projectId={PROJECT}
      sourceId={MEDIA}
      source={media({ mediaType: 'image/png', title: 'A scan' })}
    />,
    { documents },
  )

  // By role rather than by test id: an `<img>` with no accessible name is a
  // screen-reader dead end, and `documentLabel` is what supplies it.
  expect(await screen.findByRole('img', { name: 'A scan' })).toBeInTheDocument()
})

it('renders an audio source as an audio player', async () => {
  const documents = fakeDocuments(
    vi.fn(() => {
      throw new Error('read() must not be called for media')
    }),
  )

  renderWithContainer(
    <DocumentReader
      projectId={PROJECT}
      sourceId={MEDIA}
      source={media({ mediaType: 'audio/mpeg' })}
    />,
    { documents },
  )

  expect((await screen.findByTestId('media-player')).tagName).toBe('AUDIO')
})

it('does not attempt to read text for a media source', async () => {
  // Fails if the reader still calls `read()` on selection: the text route
  // answers 404 for media, and the pane would show an error where a video
  // belongs. The stub throwing is not the assertion -- react-query would
  // swallow it into an `ErrorBox` -- so both the absent call and the absent
  // error are checked.
  const read = vi.fn(() => {
    throw new Error('read() must not be called for media')
  })
  const documents = fakeDocuments(read)

  renderWithContainer(<DocumentReader projectId={PROJECT} sourceId={MEDIA} source={media()} />, {
    documents,
  })

  await screen.findByTestId('media-player')
  expect(read).not.toHaveBeenCalled()
  expect(screen.queryByText(/must not be called/)).not.toBeInTheDocument()
})

it('says a source is stored rather than showing nothing, for bytes no browser plays', async () => {
  // A `<video>` pointed at a zip renders an empty black box with no error, and
  // this pane would look broken rather than honest. The fallback names the
  // type and offers the bytes.
  const documents = fakeDocuments(
    vi.fn(() => {
      throw new Error('read() must not be called for media')
    }),
  )

  renderWithContainer(
    <DocumentReader
      projectId={PROJECT}
      sourceId={MEDIA}
      source={media({ mediaType: 'application/zip' })}
    />,
    { documents },
  )

  expect(await screen.findByRole('link', { name: /open/i })).toHaveAttribute(
    'href',
    `/api/projects/${PROJECT}/sources/m1/content`,
  )
  // Two of them: the sentence, and the digest line under it that names the
  // type on every media source whether or not it plays.
  expect(screen.getAllByText(/application\/zip/).length).toBeGreaterThan(0)
  expect(screen.queryByTestId('media-player')).not.toBeInTheDocument()
})

it('reports an error rather than an empty pane when the read fails', async () => {
  const documents = fakeDocuments(
    vi.fn<DocumentRepository['read']>().mockRejectedValue(new Error('boom')),
  )

  renderWithContainer(<DocumentReader projectId={PROJECT} sourceId={SOURCE} source={null} />, {
    documents,
  })

  expect(await screen.findByText(/boom/)).toBeInTheDocument()
})

it('says so when a video source cannot load its bytes', async () => {
  // A dangling reference -- the record is in the corpus and the blob is gone,
  // which the content route answers 410 for -- reaches this component as an
  // `error` event on the element and nothing else. Before `onError` the pane
  // rendered an inert black box, indistinguishable from a network hiccup or a
  // codec this browser will not play, which is the one surface where the
  // design's "detectable rather than silent" promise was not kept.
  //
  // Fired rather than provoked: jsdom loads no media and would never emit the
  // event on its own, so the assertion is about what the handler does, not
  // about when the browser calls it.
  const documents = fakeDocuments(
    vi.fn(() => {
      throw new Error('read() must not be called for media')
    }),
  )

  renderWithContainer(<DocumentReader projectId={PROJECT} sourceId={MEDIA} source={media()} />, {
    documents,
  })
  fireEvent.error(await screen.findByTestId('media-player'))

  expect(screen.getByText(/could not be loaded/i)).toBeInTheDocument()
  expect(screen.queryByTestId('media-player')).not.toBeInTheDocument()
})

it('says so when an image source cannot load its bytes', async () => {
  // The `<img>` branch has its own `onError`, and would have kept the broken
  // -image glyph if only the media elements had been wired. Covered
  // separately for that reason: one test over `<video>` would pass with the
  // image left silent.
  const documents = fakeDocuments(
    vi.fn(() => {
      throw new Error('read() must not be called for media')
    }),
  )

  renderWithContainer(
    <DocumentReader
      projectId={PROJECT}
      sourceId={MEDIA}
      source={media({ mediaType: 'image/png', title: 'A scan' })}
    />,
    { documents },
  )
  fireEvent.error(await screen.findByRole('img', { name: 'A scan' }))

  expect(screen.getByText(/could not be loaded/i)).toBeInTheDocument()
  expect(screen.queryByRole('img', { name: 'A scan' })).not.toBeInTheDocument()
})
