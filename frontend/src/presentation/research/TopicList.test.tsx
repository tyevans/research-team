import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import type { TopicRepository } from '@application/ports/repositories.ts'
import type { Dispatch } from '@domain/research/dispatch.ts'
import type { TopicView } from '@domain/research/topic.ts'
import { EventIndex } from '@domain/session/event-index.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
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

const emptyBoard = { running: null, queued: [], finished: [] }

/** `TopicList` calls `list`, `dispatchStatus`, and on Manage `read` -- it
 *  never sets a status or touches a sub-question itself, that is
 *  `TopicStatusDialog`'s job once it is open. Those stay stubs that fail
 *  loudly if that assumption ever stops holding.
 *
 * `dispatchStatus` defaults to an empty board rather than throwing, because
 * every test here renders a list and the list reads it unconditionally --
 * a throwing default would make every unrelated test assert on dispatch. */
const fakeTopics = (
  list: TopicRepository['list'],
  over: Partial<TopicRepository> = {},
): TopicRepository => ({
  list,
  dispatchStatus: vi.fn<TopicRepository['dispatchStatus']>().mockResolvedValue(emptyBoard),
  dispatch: vi.fn(() => {
    throw new Error('dispatch was not stubbed for this test')
  }),
  cancelDispatch: vi.fn(() => {
    throw new Error('cancelDispatch was not stubbed for this test')
  }),
  // Resolves rather than throwing: opening Manage renders the dialog, which
  // renders `TopicDocuments`, which reads this.
  documents: vi.fn().mockResolvedValue({
    directory: '/topics/00-a-topic',
    sessionId: null,
    at: ScrubPoint.head(),
    documents: [],
  }),
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
  ...over,
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
    pushDispatch: (projectId: string) =>
      act(() => {
        listener?.onFrame({
          kind: 'dispatch',
          projectId,
          dispatch: {
            dispatchId: 'd1',
            topicId: OTHER,
            action: 'understanding',
            status: 'running',
            question: 'q',
            position: null,
            path: null,
            sessionId: null,
            detail: null,
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

/** Triggers are not on the row any more.
 *
 * This replaces a test that asserted the opposite — that each row carried its
 * own triggers and not its neighbour's — and the reversal is deliberate rather
 * than a casualty. A trigger is prose of unbounded length, and a row whose
 * height depends on its content breaks the contract a virtualizer estimates
 * against: L-F8 records that as a 122px hole at three projects. `TopicDetail`,
 * which the Manage dialog shows, renders them.
 *
 * The row still *marks* the topic — `needs-attention` is asserted below — so
 * what is lost is the wording, not the signal. And `matchesTopic` still
 * searches triggers, which is tested in the domain: typing a trigger's name
 * into the filter still finds the row it belongs to, which is the one job the
 * text on the row was doing.
 *
 * Fails if the triggers list comes back: it asserts an absence.
 */
it('keeps a topic’s triggers off its row, where they would make its height depend on its content', async () => {
  const topics = fakeTopics(
    vi.fn<TopicRepository['list']>().mockResolvedValue([
      topic({
        topicId: TopicId('44444444-4444-4444-4444-444444444444'),
        question: 'Has a trigger',
        triggers: ['topic.never_investigated'],
        needsAttention: true,
      }),
    ]),
  )

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics })

  const row = (await screen.findByText('Has a trigger')).closest('.ent-topic-row')
  expect(row).not.toBeNull()
  expect(row!.textContent).not.toContain('topic.never_investigated')
  // The signal survives the wording: this is what paints the urgency edge.
  expect(row).toHaveClass('needs-attention')
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

// ---------------- dispatch ----------------

const dispatched = (over: Partial<Dispatch> = {}): Dispatch => ({
  dispatchId: 'd1',
  topicId: '22222222-2222-2222-2222-222222222222',
  action: 'understanding',
  status: 'running',
  question: 'q',
  position: null,
  path: null,
  sessionId: null,
  detail: null,
  ...over,
})

it('offers to write our understanding of a topic', async () => {
  const dispatch = vi.fn<TopicRepository['dispatch']>().mockResolvedValue(dispatched())
  const topics = fakeTopics(
    vi
      .fn<TopicRepository['list']>()
      .mockResolvedValue([topic({ question: 'Who funded the study?', sources: 2 })]),
    { dispatch },
  )

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics })

  await screen.findByText('Who funded the study?')
  await userEvent.click(screen.getByRole('button', { name: /understanding/i }))

  await waitFor(() =>
    expect(dispatch).toHaveBeenCalledWith(
      PROJECT,
      TopicId('22222222-2222-2222-2222-222222222222'),
      'understanding',
    ),
  )
})

it('will not offer to synthesise a topic nothing has been gathered for', async () => {
  // The one conditionally disabled control in this feature, and it earns it:
  // with no sources and no findings there is nothing to synthesise, and the
  // result would be the model's own prior knowledge presented as project
  // findings. Confabulation that looks like a deliverable.
  const topics = fakeTopics(
    vi
      .fn<TopicRepository['list']>()
      .mockResolvedValue([topic({ question: 'Untouched?', sources: 0, findings: 0 })]),
  )

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics })

  await screen.findByText('Untouched?')
  expect(screen.getByRole('button', { name: /understanding/i })).toBeDisabled()
})

it('shows a running dispatch on its own row and not on the others', async () => {
  const other = TopicId('33333333-3333-3333-3333-333333333333')
  const topics = fakeTopics(
    vi
      .fn<TopicRepository['list']>()
      .mockResolvedValue([
        topic({ question: 'Running one', sources: 1 }),
        topic({ topicId: other, question: 'Quiet one', sources: 1 }),
      ]),
    {
      dispatchStatus: vi.fn<TopicRepository['dispatchStatus']>().mockResolvedValue({
        running: dispatched({ status: 'running' }),
        queued: [],
        finished: [],
      }),
    },
  )

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics })

  const running = await screen.findByText(/understanding · running/i)
  expect(running).toBeInTheDocument()
  expect(screen.getAllByText(/understanding · running/i)).toHaveLength(1)
})

it('shows a queued dispatch with its position', async () => {
  const topics = fakeTopics(
    vi
      .fn<TopicRepository['list']>()
      .mockResolvedValue([topic({ question: 'Waiting', sources: 1 })]),
    {
      dispatchStatus: vi.fn<TopicRepository['dispatchStatus']>().mockResolvedValue({
        running: null,
        queued: [dispatched({ status: 'queued', position: 2 })],
        finished: [],
      }),
    },
  )

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics })

  expect(await screen.findByText(/queued · 2nd/i)).toBeInTheDocument()
})

it('keeps a failed dispatch on the row, with its reason', async () => {
  // It must persist rather than vanish on the next render: a chip that
  // disappears is how a reader concludes the button does nothing.
  const topics = fakeTopics(
    vi.fn<TopicRepository['list']>().mockResolvedValue([topic({ question: 'Broke', sources: 1 })]),
    {
      dispatchStatus: vi.fn<TopicRepository['dispatchStatus']>().mockResolvedValue({
        running: null,
        queued: [],
        finished: [dispatched({ status: 'failed', detail: 'model timed out' })],
      }),
    },
  )

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics })

  expect(await screen.findByText(/model timed out/i)).toBeInTheDocument()
})

it('re-reads the board when a dispatch frame names this project', async () => {
  const feed = fakeStream()
  const dispatchStatus = vi
    .fn<TopicRepository['dispatchStatus']>()
    .mockResolvedValue({ running: null, queued: [], finished: [] })
  const topics = fakeTopics(
    vi.fn<TopicRepository['list']>().mockResolvedValue([topic({ question: 'Anything' })]),
    { dispatchStatus },
  )

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics, stream: feed.stream })

  await screen.findByText('Anything')
  feed.pushDispatch(PROJECT)

  await waitFor(() => expect(dispatchStatus).toHaveBeenCalledTimes(2), { timeout: 2_000 })
})

it('ignores a dispatch frame for another project', async () => {
  // These frames are project-addressed precisely so a subscriber can tell.
  // Without the check, every open research pane would re-read its own board
  // whenever any project dispatched anything.
  const feed = fakeStream()
  const dispatchStatus = vi
    .fn<TopicRepository['dispatchStatus']>()
    .mockResolvedValue({ running: null, queued: [], finished: [] })
  const topics = fakeTopics(
    vi.fn<TopicRepository['list']>().mockResolvedValue([topic({ question: 'Anything' })]),
    { dispatchStatus },
  )

  renderWithContainer(<TopicList projectId={PROJECT} />, { topics, stream: feed.stream })

  await screen.findByText('Anything')
  feed.pushDispatch(ProjectId('99999999-9999-9999-9999-999999999999'))

  await new Promise((resolve) => setTimeout(resolve, FRAME_DEBOUNCE_MS * 2))
  expect(dispatchStatus).toHaveBeenCalledTimes(1)
})
