import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import type { TopicRepository } from '@application/ports/repositories.ts'
import type { TopicView } from '@domain/research/topic.ts'
import { EventIndex } from '@domain/session/event-index.ts'
import { ProjectId, SessionId, TopicId } from '@domain/shared/identifier.ts'

import { StreamProvider } from '../shell/StreamProvider.tsx'
import { FRAME_DEBOUNCE_MS } from '../shell/use-frame-refresh.ts'
import { TopicList } from './TopicList.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')
/** The topic a pushed frame names. Deliberately not one of the topics any
 *  test lists: a frame says *something* moved, and the list is re-read
 *  wholesale rather than patched from the frame's own id. */
const OTHER = TopicId('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')

const topic = (over: Partial<TopicView> = {}): TopicView => ({
  topicId: TopicId('22222222-2222-2222-2222-222222222222'),
  question: 'q',
  status: 'open',
  sources: 0,
  findings: 0,
  openSubQuestions: 0,
  triggers: [],
  needsAttention: false,
  isBlocked: false,
  ...over,
})

/** `TopicList` only calls `list` and, on Manage, `read` -- it never sets a
 *  status or touches a sub-question itself, that is `TopicStatusDialog`'s job
 *  once it is open. Those three stay stubs that fail loudly if that
 *  assumption ever stops holding. */
const fakeTopics = (list: TopicRepository['list']): TopicRepository => ({
  list,
  read: vi.fn(() => {
    throw new Error('read was not stubbed for this test')
  }),
  setStatus: vi.fn(() => {
    throw new Error('TopicList should never call setStatus()')
  }),
  addSubQuestion: vi.fn(() => {
    throw new Error('TopicList should never call addSubQuestion()')
  }),
  resolveSubQuestion: vi.fn(() => {
    throw new Error('TopicList should never call resolveSubQuestion()')
  }),
  startSeed: vi.fn(() => {
    throw new Error('TopicList should never call startSeed()')
  }),
  seedStatus: vi.fn(() => {
    throw new Error('TopicList should never call seedStatus()')
  }),
})

/** Mirrors `SeedPanel.test.tsx`'s fake stream, so a live-update assertion
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
    push: (change = 'TopicOpened') =>
      act(() => {
        listener?.onFrame({ kind: 'topic', topicId: OTHER, change })
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

/** Mirrors `Workers.test.tsx`'s harness: a fake container behind the same
 *  providers the real app wraps every view in. The `StreamProvider` is not
 *  decoration -- `TopicList` subscribes to the feed, and a harness without
 *  one would be testing a component the application never renders. */
const renderWithContainer = (ui: ReactElement, parts: Partial<AppContainer>) => {
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

it('renders every topic’s question', async () => {
  const topics = fakeTopics(
    vi.fn<TopicRepository['list']>().mockResolvedValue([
      topic({ question: 'Who funded the study?' }),
      topic({
        topicId: TopicId('33333333-3333-3333-3333-333333333333'),
        question: 'When did it end?',
      }),
    ]),
  )

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics })

  expect(await screen.findByText('Who funded the study?')).toBeInTheDocument()
  expect(screen.getByText('When did it end?')).toBeInTheDocument()
})

it('renders a topic’s triggers under its own question, not mixed with another’s', async () => {
  const topics = fakeTopics(
    vi.fn<TopicRepository['list']>().mockResolvedValue([
      topic({
        topicId: TopicId('44444444-4444-4444-4444-444444444444'),
        question: 'Has a trigger',
        triggers: ['topic.never_investigated'],
      }),
      topic({
        topicId: TopicId('55555555-5555-5555-5555-555555555555'),
        question: 'Has none',
        triggers: [],
      }),
    ]),
  )

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics })

  const withTrigger = await screen.findByText('Has a trigger')
  const row = withTrigger.closest('.topic-row')
  expect(row).not.toBeNull()
  expect(row!.textContent).toContain('topic.never_investigated')

  const withoutTrigger = screen.getByText('Has none')
  expect(withoutTrigger.closest('.topic-row')!.textContent).not.toContain(
    'topic.never_investigated',
  )
})

it('sorts a blocked topic to the top of the list', async () => {
  const topics = fakeTopics(
    vi.fn<TopicRepository['list']>().mockResolvedValue([
      topic({
        topicId: TopicId('66666666-6666-6666-6666-666666666666'),
        question: 'Ordinary topic',
      }),
      topic({
        topicId: TopicId('77777777-7777-7777-7777-777777777777'),
        question: 'Blocked topic',
        isBlocked: true,
      }),
    ]),
  )

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics })

  await screen.findByText('Ordinary topic')
  const questions = screen.getAllByRole('listitem').map((item) => item.textContent)
  expect(questions[0]).toContain('Blocked topic')
  expect(questions[1]).toContain('Ordinary topic')
})

it('says no topics exist yet rather than showing an empty box', async () => {
  const topics = fakeTopics(vi.fn<TopicRepository['list']>().mockResolvedValue([]))

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics })

  expect(await screen.findByText(/no topics/i)).toBeInTheDocument()
})

it('opens the status dialog for a topic on manage, reading its detail first', async () => {
  const list = vi
    .fn<TopicRepository['list']>()
    .mockResolvedValue([topic({ question: 'Who funded the study?' })])
  const read = vi.fn<TopicRepository['read']>().mockResolvedValue({
    topicId: TopicId('22222222-2222-2222-2222-222222222222'),
    question: 'Who funded the study?',
    status: 'open',
    sources: 0,
    findings: 0,
    openSubQuestions: 0,
    triggers: [],
    needsAttention: false,
    isBlocked: false,
    rationale: 'because it matters',
    scope: 'the whole project',
    subQuestions: [],
    sourceIds: [],
    findingNotes: [],
    contested: false,
  })

  const topics = { ...fakeTopics(list), read }

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics })

  await userEvent.click(await screen.findByRole('button', { name: /manage/i }))

  expect(read).toHaveBeenCalledWith(PROJECT, TopicId('22222222-2222-2222-2222-222222222222'))
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
})

it('narrows the queue to what needs a person, counting blocked and flagged alike', async () => {
  const topics = fakeTopics(
    vi.fn<TopicRepository['list']>().mockResolvedValue([
      topic({ topicId: TopicId('88888888-8888-8888-8888-888888888888'), question: 'Just open' }),
      topic({
        topicId: TopicId('99999999-9999-9999-9999-999999999999'),
        question: 'Is blocked',
        isBlocked: true,
      }),
      topic({
        topicId: TopicId('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'),
        question: 'Is flagged',
        needsAttention: true,
      }),
    ]),
  )

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics })

  await screen.findByText('Just open')
  await userEvent.click(screen.getByRole('radio', { name: /needs you/i }))

  expect(screen.getByText('Is blocked')).toBeInTheDocument()
  expect(screen.getByText('Is flagged')).toBeInTheDocument()
  expect(screen.queryByText('Just open')).not.toBeInTheDocument()
})

it('counts each slice over the whole queue, not over what is currently shown', async () => {
  const topics = fakeTopics(
    vi.fn<TopicRepository['list']>().mockResolvedValue([
      topic({ topicId: TopicId('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'), question: 'Just open' }),
      topic({
        topicId: TopicId('cccccccc-cccc-cccc-cccc-cccccccccccc'),
        question: 'Is blocked',
        isBlocked: true,
      }),
    ]),
  )

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics })

  await screen.findByText('Just open')
  // Still 2 and 1 after filtering down to one row: the counts describe the
  // queue, so they are what tells a reader what the other tabs hold.
  expect(screen.getByRole('radio', { name: /all/i }).textContent).toContain('2')
  await userEvent.click(screen.getByRole('radio', { name: /needs you/i }))
  expect(screen.getByRole('radio', { name: /all/i }).textContent).toContain('2')
  expect(screen.getByRole('radio', { name: /needs you/i }).textContent).toContain('1')
})

it('filters on the search term, matching a trigger as well as a question', async () => {
  const topics = fakeTopics(
    vi.fn<TopicRepository['list']>().mockResolvedValue([
      topic({
        topicId: TopicId('dddddddd-dddd-dddd-dddd-dddddddddddd'),
        question: 'Do dogs dream?',
        triggers: ['topic.contested'],
      }),
      topic({ topicId: TopicId('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'), question: 'Do cats?' }),
    ]),
  )

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics })

  await screen.findByText('Do cats?')
  await userEvent.type(screen.getByLabelText('Filter topics'), 'contested')

  expect(screen.getByText('Do dogs dream?')).toBeInTheDocument()
  expect(screen.queryByText('Do cats?')).not.toBeInTheDocument()
})

it('says the filter is hiding the queue, not that the project has no topics', async () => {
  const topics = fakeTopics(
    vi
      .fn<TopicRepository['list']>()
      .mockResolvedValue([topic({ question: 'Who funded the study?' })]),
  )

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics })

  await screen.findByText('Who funded the study?')
  await userEvent.type(screen.getByLabelText('Filter topics'), 'zzzz')

  expect(screen.getByText(/no topics match/i)).toBeInTheDocument()
})

it('re-reads the queue when a topic frame says one was opened', async () => {
  // The bug this pins: a seeding run opens topics, the frames arrive, and the
  // list showed the same rows until the reader hit reload. Asserting the
  // second `list` call and the new row, not just the call -- an invalidation
  // that fired against a misspelt key would still leave the screen stale.
  const feed = fakeStream()
  const list = vi
    .fn<TopicRepository['list']>()
    .mockResolvedValueOnce([topic({ question: 'Who funded the study?' })])
    .mockResolvedValue([
      topic({ question: 'Who funded the study?' }),
      topic({ topicId: OTHER, question: 'Freshly seeded' }),
    ])

  renderWithContainer(<TopicList projectId={PROJECT} />, {
    topics: fakeTopics(list),
    stream: feed.stream,
  })

  await screen.findByText('Who funded the study?')
  feed.push()

  // Longer than `FRAME_DEBOUNCE_MS`: the refresh is deliberately not
  // immediate, because a run opens eight topics in a burst.
  expect(await screen.findByText('Freshly seeded', {}, { timeout: 2_000 })).toBeInTheDocument()
})

it('re-reads once for a burst of topic frames, not once per frame', async () => {
  // A seeding run opens eight topics in a row. Without the debounce this page
  // would fire eight list reads while also drawing a force-directed graph.
  const feed = fakeStream()
  const list = vi
    .fn<TopicRepository['list']>()
    .mockResolvedValue([topic({ question: 'Who funded the study?' })])

  renderWithContainer(<TopicList projectId={PROJECT} />, {
    topics: fakeTopics(list),
    stream: feed.stream,
  })

  await screen.findByText('Who funded the study?')
  for (let i = 0; i < 8; i += 1) feed.push()

  await waitFor(() => expect(list).toHaveBeenCalledTimes(2), { timeout: 2_000 })
  expect(list).toHaveBeenCalledTimes(2)
})

it('ignores a log frame, which says nothing about this project’s topics', async () => {
  // Scope, asserted: the tree refetches on every log frame, and this list
  // doing the same would re-read the queue on every token of every turn.
  const feed = fakeStream()
  const list = vi
    .fn<TopicRepository['list']>()
    .mockResolvedValue([topic({ question: 'Who funded the study?' })])

  renderWithContainer(<TopicList projectId={PROJECT} />, {
    topics: fakeTopics(list),
    stream: feed.stream,
  })

  await screen.findByText('Who funded the study?')
  feed.pushLog()

  await new Promise((resolve) => setTimeout(resolve, FRAME_DEBOUNCE_MS * 2))
  expect(list).toHaveBeenCalledTimes(1)
})
