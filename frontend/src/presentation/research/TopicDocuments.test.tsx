import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import type { TopicRepository } from '@application/ports/repositories.ts'
import type { TopicDocuments as Documents } from '@domain/research/topic-document.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import { ProjectId, SessionId, TopicId } from '@domain/shared/identifier.ts'

import { StreamProvider } from '../shell/StreamProvider.tsx'
import { FRAME_DEBOUNCE_MS } from '../shell/use-frame-refresh.ts'
import { TopicDocuments } from './TopicDocuments.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')
const TOPIC = TopicId('22222222-2222-2222-2222-222222222222')
const WRITER = SessionId('cccccccc-cccc-cccc-cccc-cccccccccccc')
const PATH = '/topics/00-how-does-spacing-work/understanding.md'

const board = (over: Partial<Documents> = {}): Documents => ({
  directory: '/topics/00-how-does-spacing-work',
  sessionId: WRITER,
  at: ScrubPoint.head(),
  documents: [{ path: FilePath.of(PATH), name: 'understanding.md' }],
  ...over,
})

const fakeStream = () => {
  let listener: EventStreamListener | null = null
  return {
    stream: {
      connect: (received) => {
        listener = received
      },
      disconnect: () => {
        listener = null
      },
    } satisfies EventStream,
    pushDispatch: (projectId: string, topicId: string) =>
      act(() => {
        listener?.onFrame({
          kind: 'dispatch',
          projectId,
          dispatch: {
            dispatchId: 'd1',
            topicId,
            action: 'understanding',
            status: 'done',
            question: 'q',
            position: null,
            path: PATH,
            sessionId: WRITER,
            detail: null,
          },
        })
      }),
  }
}

const renderPane = (ui: ReactElement, parts: Partial<AppContainer>) => {
  const container = { stream: fakeStream().stream, ...parts } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <StreamProvider>{children}</StreamProvider>
      </ContainerProvider>
    </QueryClientProvider>
  )
  return render(ui, { wrapper })
}

const parts = (
  documents: Documents,
  over: { contents?: string; parse?: unknown } = {},
): Partial<AppContainer> =>
  ({
    topics: { documents: vi.fn().mockResolvedValue(documents) } as unknown as TopicRepository,
    workspace: { readFile: vi.fn().mockResolvedValue(over.contents ?? '# What we know') },
    lessons: {
      parse: vi.fn().mockResolvedValue(over.parse ?? { path: PATH, blocks: [] }),
      progress: vi.fn().mockResolvedValue(new Map()),
      submitAttempt: vi.fn(),
      saveChecklist: vi.fn(),
    },
  }) as unknown as Partial<AppContainer>

it('names the directory a dispatch will write to when nothing is there yet', async () => {
  // Not "no documents": a reader who dispatched a moment ago wants to know
  // *where* it will appear, and one whose topic moved in the list needs the
  // path to notice the directory it was written to is not this one.
  renderPane(
    <TopicDocuments projectId={PROJECT} topicId={TOPIC} />,
    parts(board({ documents: [] })),
  )

  expect(await screen.findByText(/\/topics\/00-how-does-spacing-work/)).toBeInTheDocument()
})

it('lists what was written about this topic', async () => {
  renderPane(<TopicDocuments projectId={PROJECT} topicId={TOPIC} />, parts(board()))

  expect(await screen.findByRole('button', { name: 'understanding.md' })).toBeInTheDocument()
})

it('renders a document read from the session the listing named', async () => {
  // The load-bearing assertion of the whole route: the file is on a session
  // the research view has no other handle on, and reading it from the wrong
  // one is a 404 rather than a wrong answer.
  const container = parts(board(), { contents: '# Spacing works' })
  renderPane(<TopicDocuments projectId={PROJECT} topicId={TOPIC} />, container)

  await userEvent.click(await screen.findByRole('button', { name: 'understanding.md' }))

  await waitFor(() => expect(screen.getByText('Spacing works')).toBeInTheDocument())
  const workspace = container.workspace as unknown as { readFile: ReturnType<typeof vi.fn> }
  expect(workspace.readFile).toHaveBeenCalledWith(WRITER, expect.anything(), ScrubPoint.head())
})

it('reads a released project’s files at the tip, not at the session’s HEAD', async () => {
  // A project nobody holds has its files at the *tip*, a position in a session
  // that may have run on past it. Reading that session at HEAD would show
  // files the project does not have. Would pass with `at` ignored if every
  // fixture used HEAD, which is why this one does not.
  const container = parts(board({ at: ScrubPoint.fromNullable(12) }))
  renderPane(<TopicDocuments projectId={PROJECT} topicId={TOPIC} />, container)

  await userEvent.click(await screen.findByRole('button', { name: 'understanding.md' }))

  const workspace = container.workspace as unknown as { readFile: ReturnType<typeof vi.fn> }
  await waitFor(() =>
    expect(workspace.readFile).toHaveBeenCalledWith(
      WRITER,
      expect.anything(),
      ScrubPoint.fromNullable(12),
    ),
  )
})

it('re-reads the listing when this topic’s dispatch finishes', async () => {
  const feed = fakeStream()
  const container = parts(board({ documents: [] }))
  renderPane(<TopicDocuments projectId={PROJECT} topicId={TOPIC} />, {
    ...container,
    stream: feed.stream,
  })

  await screen.findByText(/\/topics\/00-how-does-spacing-work/)
  feed.pushDispatch(PROJECT, TOPIC)

  const topics = container.topics as unknown as { documents: ReturnType<typeof vi.fn> }
  await waitFor(() => expect(topics.documents).toHaveBeenCalledTimes(2), { timeout: 2_000 })
})

it('ignores a dispatch on another topic', async () => {
  // A listing is one directory, and another topic's dispatch cannot change it.
  // Without the check, opening one topic would re-read its documents every
  // time any of the project's forty topics moved.
  const feed = fakeStream()
  const container = parts(board({ documents: [] }))
  renderPane(<TopicDocuments projectId={PROJECT} topicId={TOPIC} />, {
    ...container,
    stream: feed.stream,
  })

  await screen.findByText(/\/topics\/00-how-does-spacing-work/)
  feed.pushDispatch(PROJECT, TopicId('99999999-9999-9999-9999-999999999999'))

  await new Promise((resolve) => setTimeout(resolve, FRAME_DEBOUNCE_MS * 2))
  const topics = container.topics as unknown as { documents: ReturnType<typeof vi.fn> }
  expect(topics.documents).toHaveBeenCalledTimes(1)
})
