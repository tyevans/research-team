import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream } from '@application/ports/event-stream.ts'
import type { DocumentRepository } from '@application/ports/repositories.ts'
import { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { StreamProvider } from '../shell/StreamProvider.tsx'
import { DocumentUpload, slugify } from './DocumentUpload.tsx'

const project = ProjectId('11111111-1111-1111-1111-111111111111')

/** Copied from `DocumentList.test.tsx` -- there is no MSW here, the port is
 *  what gets faked, and every method throws until a test stubs it so a test
 *  that reaches an unstubbed call fails at the call rather than passing
 *  silently on `undefined`. */
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

// Held in a local rather than read back off `documents.create`:
// `expect(obj.fn)` trips `@typescript-eslint/unbound-method`, which is a lint
// gate here (see `DocumentList.test.tsx`'s `queues the document whose extract
// control was pressed` for the same pattern).
const create = vi.fn<DocumentRepository['create']>().mockResolvedValue({
  sourceId: SourceId('hello'),
  kind: 'text',
  charCount: 5,
  derivedFrom: null,
  degradations: [],
  sha256: 'x',
  uri: null,
  title: 'Hello',
  publishedAt: null,
  note: null,
  fetchedAt: null,
  droppedReason: null,
  extracted: false,
})

const uploadMedia = vi.fn<DocumentRepository['uploadMedia']>().mockResolvedValue({
  sourceId: 'keynote',
  kind: 'media',
  mediaType: 'video/mp4',
  byteCount: 12,
  sha256: 'x',
  uri: null,
  title: 'keynote',
  publishedAt: null,
  note: null,
  fetchedAt: null,
  droppedReason: null,
  extracted: false,
} as Awaited<ReturnType<DocumentRepository['uploadMedia']>>)

const documents = fakeDocuments({ create, uploadMedia })

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

// Shared `documents` fake across tests -- cleared rather than rebuilt per
// test so the wrapper closure stays simple, but a call recorded by one test
// would otherwise leak into the next's `toHaveBeenCalledWith` assertion.
afterEach(() => {
  create.mockClear()
  uploadMedia.mockClear()
})

it('posts a picked media file rather than reading it as text', async () => {
  // `file.text()` on a video decodes megabytes of binary into a string and
  // stores the mojibake as a document -- which succeeds, and is the failure
  // this asserts against. The media path never touches `create`.
  const user = userEvent.setup()
  render(<DocumentUpload projectId={project} onClose={vi.fn()} />, { wrapper })

  const file = new File(['not really a video'], 'keynote.mp4', { type: 'video/mp4' })
  await user.upload(screen.getByLabelText('Media file'), file)
  await waitFor(() => {
    expect(screen.getByLabelText('Identifier')).toHaveValue('keynote')
  })
  await user.click(screen.getByRole('button', { name: 'Add document' }))

  await waitFor(() => {
    expect(uploadMedia).toHaveBeenCalledWith(project, {
      sourceId: 'keynote',
      file,
      title: 'keynote',
    })
  })
  expect(create).not.toHaveBeenCalled()
})

it('does not ask for text once a media file is picked', async () => {
  // The text area is the text path's required field, and a media upload has no
  // text to give -- leaving it on screen would ask for something that is about
  // to be ignored, and leaving its guard armed would refuse the upload.
  const user = userEvent.setup()
  render(<DocumentUpload projectId={project} onClose={vi.fn()} />, { wrapper })

  await user.upload(
    screen.getByLabelText('Media file'),
    new File(['x'], 'keynote.mp4', { type: 'video/mp4' }),
  )

  await waitFor(() => {
    expect(screen.queryByLabelText('Text')).not.toBeInTheDocument()
  })
})

it('lets a media file be un-picked through the picker that set it', async () => {
  // The native picker's own "clear" fires a change event with no file. A
  // handler that only acted on a present file left `media` set while the
  // control showed nothing: the Text field stayed hidden and the form still
  // posted multipart with a file the reader believed they had removed. Fails
  // against `if (file) handleMedia(file)`.
  const user = userEvent.setup()
  render(<DocumentUpload projectId={project} onClose={vi.fn()} />, { wrapper })

  const picker = screen.getByLabelText('Media file')
  await user.upload(picker, new File(['x'], 'keynote.mp4', { type: 'video/mp4' }))
  await waitFor(() => {
    expect(screen.queryByLabelText('Text')).not.toBeInTheDocument()
  })

  await user.upload(picker, [])

  expect(await screen.findByLabelText('Text')).toBeInTheDocument()
})

it('fills the text and the title from a picked file', async () => {
  const user = userEvent.setup()
  render(<DocumentUpload projectId={project} onClose={vi.fn()} />, { wrapper })

  await user.upload(
    screen.getByLabelText('Text file'),
    new File(['the contents'], 'a-paper.md', { type: 'text/markdown' }),
  )

  await waitFor(() => {
    expect(screen.getByLabelText('Text')).toHaveValue('the contents')
  })
  expect(screen.getByLabelText('Title')).toHaveValue('a-paper')
})

it('sends what is on screen', async () => {
  const user = userEvent.setup()
  render(<DocumentUpload projectId={project} onClose={vi.fn()} />, { wrapper })

  await user.type(screen.getByLabelText('Title'), 'Hello')
  await user.type(screen.getByLabelText('Text'), 'hello')
  await user.click(screen.getByRole('button', { name: 'Add document' }))

  await waitFor(() => {
    expect(create).toHaveBeenCalledWith(project, {
      sourceId: 'hello',
      text: 'hello',
      title: 'Hello',
    })
  })
})

it('refuses an empty id before it calls the server', async () => {
  // The id is the citation key and the corpus keys on it, so a blank one is
  // refused here rather than spending a round-trip to be told.
  const user = userEvent.setup()
  render(<DocumentUpload projectId={project} onClose={vi.fn()} />, { wrapper })

  await user.type(screen.getByLabelText('Text'), 'hello')
  await user.clear(screen.getByLabelText('Identifier'))
  await user.click(screen.getByRole('button', { name: 'Add document' }))

  expect(create).not.toHaveBeenCalled()
})

it('refuses empty text before it calls the server', async () => {
  // Red before the guard: the server caps length and sets no minimum, so a
  // blank text area was stored and listed at `char_count: 0`.
  const user = userEvent.setup()
  render(<DocumentUpload projectId={project} onClose={vi.fn()} />, { wrapper })

  await user.type(screen.getByLabelText('Title'), 'Hello')
  await user.click(screen.getByRole('button', { name: 'Add document' }))

  expect(create).not.toHaveBeenCalled()
})

// Directly rather than only through the form: `slugify` produces the
// identifier a reader overtypes, the identifier is the citation key, and a
// bad default orphans citations silently. The form test above only ever sees
// it applied to one well-behaved title.
it.each([
  ['Hello', 'hello'],
  ['Two Words', 'two-words'],
  // Punctuation is not stripped, it is a separator: every run of
  // non-alphanumerics collapses to a single `-`, and leading/trailing ones
  // are trimmed off rather than left as an edge dash.
  ["Gödel's Proof", 'g-del-s-proof'],
  ['  spaced  out  ', 'spaced-out'],
  ['--already--', 'already'],
  ['???', ''],
])('slugifies %j to %j', (input, expected) => {
  expect(slugify(input)).toBe(expected)
})
