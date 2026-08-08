import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { TopicRepository } from '@application/ports/repositories.ts'
import type { TopicView } from '@domain/research/topic.ts'
import { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import { TopicList } from './TopicList.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

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

/** Mirrors `Workers.test.tsx`'s harness: a fake container behind the same
 *  providers the real app wraps every view in. */
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
