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

import { TopicStatusDialog } from './TopicStatusDialog.tsx'

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

/** This suite never exercises `list`/`read`/`addSubQuestion`/`resolveSubQuestion`
 *  -- only `setStatus` -- so the rest are stubs that fail loudly if that
 *  assumption stops holding, the same convention `TopicList.test.tsx` uses. */
const fakeTopics = (over: Partial<TopicRepository> = {}): TopicRepository => ({
  list: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call list()')
  }),
  read: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call read()')
  }),
  setStatus: vi.fn(() => {
    throw new Error('setStatus was not stubbed for this test')
  }),
  addSubQuestion: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call addSubQuestion()')
  }),
  resolveSubQuestion: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call resolveSubQuestion()')
  }),
  startSeed: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call startSeed()')
  }),
  seedStatus: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call seedStatus()')
  }),
  dispatch: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call dispatch()')
  }),
  dispatchStatus: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call dispatchStatus()')
  }),
  cancelDispatch: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call cancelDispatch()')
  }),
  ...over,
})

const renderDialog = (ui: ReactElement, parts: Partial<AppContainer> = {}) => {
  const container = { topics: fakeTopics(), ...parts } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>{children}</ContainerProvider>
    </QueryClientProvider>
  )
  return render(ui, { wrapper })
}

it('will not submit without a justification', async () => {
  renderDialog(<TopicStatusDialog projectId={PROJECT} topic={aTopic()} onClose={vi.fn()} />)

  await userEvent.click(screen.getByRole('button', { name: /answered/i }))

  expect(screen.getByRole('button', { name: /save/i })).toBeDisabled()
})

it('will not submit a whitespace-only justification', async () => {
  renderDialog(<TopicStatusDialog projectId={PROJECT} topic={aTopic()} onClose={vi.fn()} />)

  await userEvent.click(screen.getByRole('button', { name: /answered/i }))
  await userEvent.type(screen.getByLabelText(/justification/i), '   ')

  expect(screen.getByRole('button', { name: /save/i })).toBeDisabled()
})

it('traps focus while it is open', async () => {
  // The drawer shipped without this and it had to be fixed after the fact
  // (commit d5f9b64) -- this dialog must not reintroduce the same gap.
  renderDialog(<TopicStatusDialog projectId={PROJECT} topic={aTopic()} onClose={vi.fn()} />)

  await userEvent.tab()
  expect(document.activeElement).not.toBe(document.body)
})

it('restores focus to what was focused before it opened, on close', async () => {
  const opener = document.createElement('button')
  opener.textContent = 'open'
  document.body.appendChild(opener)
  opener.focus()

  const { unmount } = renderDialog(
    <TopicStatusDialog projectId={PROJECT} topic={aTopic()} onClose={vi.fn()} />,
  )
  expect(document.activeElement).not.toBe(opener)

  unmount()
  expect(document.activeElement).toBe(opener)
  opener.remove()
})

it('closes on escape', async () => {
  const onClose = vi.fn()
  renderDialog(<TopicStatusDialog projectId={PROJECT} topic={aTopic()} onClose={onClose} />)

  await userEvent.keyboard('{Escape}')

  expect(onClose).toHaveBeenCalled()
})

it('does not offer the topic’s current status as a choice', () => {
  renderDialog(
    <TopicStatusDialog
      projectId={PROJECT}
      topic={aTopic({ status: 'investigating' })}
      onClose={vi.fn()}
    />,
  )

  expect(screen.queryByRole('button', { name: /^investigating$/i })).toBeNull()
  expect(screen.getByRole('button', { name: /^answered$/i })).toBeInTheDocument()
})

it('saves the chosen status with its justification, then closes', async () => {
  const onClose = vi.fn()
  const setStatus = vi
    .fn<TopicRepository['setStatus']>()
    .mockResolvedValue(aTopic({ status: 'answered' }))

  renderDialog(<TopicStatusDialog projectId={PROJECT} topic={aTopic()} onClose={onClose} />, {
    topics: fakeTopics({ setStatus }),
  })

  await userEvent.click(screen.getByRole('button', { name: /^answered$/i }))
  await userEvent.type(screen.getByLabelText(/justification/i), 'confirmed in the filing')
  await userEvent.click(screen.getByRole('button', { name: /save/i }))

  expect(setStatus).toHaveBeenCalledWith(
    PROJECT,
    aTopic().topicId,
    'answered',
    'confirmed in the filing',
  )
  await vi.waitFor(() => expect(onClose).toHaveBeenCalled())
})

it('reopens an answered topic back to investigating', async () => {
  const setStatus = vi
    .fn<TopicRepository['setStatus']>()
    .mockResolvedValue(aTopic({ status: 'investigating' }))

  renderDialog(
    <TopicStatusDialog
      projectId={PROJECT}
      topic={aTopic({ status: 'answered' })}
      onClose={vi.fn()}
    />,
    { topics: fakeTopics({ setStatus }) },
  )

  await userEvent.click(screen.getByRole('button', { name: /^investigating$/i }))
  await userEvent.type(screen.getByLabelText(/justification/i), 'new evidence surfaced')
  await userEvent.click(screen.getByRole('button', { name: /save/i }))

  expect(setStatus).toHaveBeenCalledWith(
    PROJECT,
    aTopic().topicId,
    'investigating',
    'new evidence surfaced',
  )
})
