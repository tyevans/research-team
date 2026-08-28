import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { TopicRepository } from '@application/ports/repositories.ts'
import type { TopicDetail } from '@domain/research/topic.ts'
import { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import { SubQuestions } from './SubQuestions.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const aTopic = (over: Partial<TopicDetail> = {}): TopicDetail => ({
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
  ...over,
})

/** This suite never exercises `list`/`read`/`setStatus` -- only the two
 *  sub-question routes -- so the rest are stubs that fail loudly if that
 *  assumption stops holding. */
const fakeTopics = (over: Partial<TopicRepository> = {}): TopicRepository => ({
  list: vi.fn(() => {
    throw new Error('SubQuestions should never call list()')
  }),
  read: vi.fn(() => {
    throw new Error('SubQuestions should never call read()')
  }),
  setStatus: vi.fn(() => {
    throw new Error('SubQuestions should never call setStatus()')
  }),
  addSubQuestion: vi.fn(() => {
    throw new Error('addSubQuestion was not stubbed for this test')
  }),
  resolveSubQuestion: vi.fn(() => {
    throw new Error('resolveSubQuestion was not stubbed for this test')
  }),
  startSeed: vi.fn(() => {
    throw new Error('SubQuestions should never call startSeed()')
  }),
  seedStatus: vi.fn(() => {
    throw new Error('SubQuestions should never call seedStatus()')
  }),
  dispatch: vi.fn(() => {
    throw new Error('SubQuestions should never call dispatch()')
  }),
  dispatchStatus: vi.fn(() => {
    throw new Error('SubQuestions should never call dispatchStatus()')
  }),
  dispatchBulk: vi.fn(() => {
    throw new Error('SubQuestions should never call dispatchBulk()')
  }),
  cancelDispatch: vi.fn(() => {
    throw new Error('SubQuestions should never call cancelDispatch()')
  }),
  documents: vi.fn(() => {
    throw new Error('SubQuestions should never call documents()')
  }),
  ...over,
})

const renderIt = (ui: ReactElement, parts: Partial<AppContainer> = {}) => {
  const container = { topics: fakeTopics(), ...parts } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>{children}</ContainerProvider>
    </QueryClientProvider>
  )
  return render(ui, { wrapper })
}

it('lists every sub-question with its resolution state', () => {
  renderIt(
    <SubQuestions
      projectId={PROJECT}
      topic={aTopic({
        subQuestions: [
          { key: 'motor', question: 'What powered it?', answer: null, resolved: false },
          { key: 'funding', question: 'Who paid?', answer: 'the state', resolved: true },
        ],
      })}
    />,
  )

  expect(screen.getByText('What powered it?')).toBeInTheDocument()
  expect(screen.getByText('Who paid?')).toBeInTheDocument()
  expect(screen.getByText('the state')).toBeInTheDocument()
})

it('adds a new sub-question with a key and question text', async () => {
  const addSubQuestion = vi.fn<TopicRepository['addSubQuestion']>().mockResolvedValue(aTopic())

  renderIt(<SubQuestions projectId={PROJECT} topic={aTopic()} />, {
    topics: fakeTopics({ addSubQuestion }),
  })

  await userEvent.type(screen.getByLabelText(/key/i), 'motor')
  await userEvent.type(screen.getByLabelText(/^question$/i), 'What powered it?')
  await userEvent.click(screen.getByRole('button', { name: /add/i }))

  expect(addSubQuestion).toHaveBeenCalledWith(
    PROJECT,
    aTopic().topicId,
    'motor',
    'What powered it?',
  )
})

it('will not add a sub-question with a blank key or question', async () => {
  renderIt(<SubQuestions projectId={PROJECT} topic={aTopic()} />)

  expect(screen.getByRole('button', { name: /add/i })).toBeDisabled()
})

it('resolves an open sub-question with its answer', async () => {
  const resolveSubQuestion = vi
    .fn<TopicRepository['resolveSubQuestion']>()
    .mockResolvedValue(aTopic())

  renderIt(
    <SubQuestions
      projectId={PROJECT}
      topic={aTopic({
        subQuestions: [
          { key: 'motor', question: 'What powered it?', answer: null, resolved: false },
        ],
      })}
    />,
    { topics: fakeTopics({ resolveSubQuestion }) },
  )

  await userEvent.type(screen.getByLabelText(/answer/i), 'a diesel engine')
  await userEvent.click(screen.getByRole('button', { name: /resolve/i }))

  expect(resolveSubQuestion).toHaveBeenCalledWith(
    PROJECT,
    aTopic().topicId,
    'motor',
    'a diesel engine',
  )
})

it('offers no resolve control for an already-resolved sub-question', () => {
  renderIt(
    <SubQuestions
      projectId={PROJECT}
      topic={aTopic({
        subQuestions: [
          { key: 'funding', question: 'Who paid?', answer: 'the state', resolved: true },
        ],
      })}
    />,
  )

  expect(screen.queryByRole('button', { name: /resolve/i })).toBeNull()
})
