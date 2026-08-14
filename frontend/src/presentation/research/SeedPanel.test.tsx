import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { useToasts } from '@application/notifications/toast-store.ts'
import { ApiError } from '@application/ports/errors.ts'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import type { TopicRepository } from '@application/ports/repositories.ts'
import type { SeedingRun } from '@domain/research/seeding.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { StreamProvider } from '../shell/StreamProvider.tsx'
import { SeedPanel } from './SeedPanel.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const run = (over: Partial<SeedingRun> = {}): SeedingRun => ({
  runId: 'r1',
  status: 'running',
  subject: 'spaced repetition',
  reply: null,
  detail: null,
  ...over,
})

/** Mirrors `ExtractionPane.test.tsx`'s fake stream, so the reconnect
 *  assertion drives the real `StreamProvider` fan-out rather than calling a
 *  prop directly. */
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
    push: (run: SeedingRun) =>
      act(() => {
        listener?.onFrame({ kind: 'seeding', projectId: PROJECT, run })
      }),
    reconnect: () =>
      act(() => {
        listener?.onReconnect(true)
      }),
  }
}

const renderWithContainer = (ui: ReactElement, parts: Partial<AppContainer>) => {
  const container = parts as unknown as AppContainer
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

const emptyStatus = () => ({ current: null, last: null })

const fakeTopics = (over: Partial<TopicRepository> = {}) => ({
  list: vi.fn(() => {
    throw new Error('SeedPanel should never call list()')
  }),
  read: vi.fn(() => {
    throw new Error('SeedPanel should never call read()')
  }),
  setStatus: vi.fn(() => {
    throw new Error('SeedPanel should never call setStatus()')
  }),
  addSubQuestion: vi.fn(() => {
    throw new Error('SeedPanel should never call addSubQuestion()')
  }),
  resolveSubQuestion: vi.fn(() => {
    throw new Error('SeedPanel should never call resolveSubQuestion()')
  }),
  seedStatus: vi.fn().mockResolvedValue(emptyStatus()),
  startSeed: vi.fn(),
  dispatch: vi.fn(() => {
    throw new Error('SeedPanel should never call dispatch()')
  }),
  dispatchStatus: vi.fn(() => {
    throw new Error('SeedPanel should never call dispatchStatus()')
  }),
  cancelDispatch: vi.fn(() => {
    throw new Error('SeedPanel should never call cancelDispatch()')
  }),
  documents: vi.fn(() => {
    throw new Error('SeedPanel should never call documents()')
  }),
  ...over,
})

it('starts a run for the typed subject and disables the control while it is active', async () => {
  const user = userEvent.setup()
  // `SeedingActivity.start` mints its running frame before the model call
  // that would name a subject -- the POST response carries none. Matched
  // here rather than fixturing a `subject` on it, or this test would not
  // have caught the panel showing "Naming topics for null" while running.
  const topics = fakeTopics({ startSeed: vi.fn().mockResolvedValue(run({ subject: null })) })
  const { stream } = fakeStream()

  renderWithContainer(<SeedPanel projectId={PROJECT} />, { topics, stream })

  const input = await screen.findByLabelText('Subject')
  await user.type(input, 'spaced repetition and memory')
  await user.click(screen.getByRole('button', { name: 'Seed topics' }))

  expect(topics.startSeed).toHaveBeenCalledWith(PROJECT, 'spaced repetition and memory', 8)
  expect(await screen.findByRole('button', { name: 'Seeding…' })).toBeDisabled()
  expect(input).toBeDisabled()
  // The subject the run carries back is null, so the status line falls back
  // to what this tab itself just asked for rather than printing "null".
  expect(screen.getByText(/Naming topics for “spaced repetition and memory”/)).toBeInTheDocument()
})

it('will not submit a blank or whitespace-only subject', async () => {
  const user = userEvent.setup()
  const topics = fakeTopics()
  const { stream } = fakeStream()

  renderWithContainer(<SeedPanel projectId={PROJECT} />, { topics, stream })

  const input = await screen.findByLabelText('Subject')
  await user.type(input, '   ')

  expect(screen.getByRole('button', { name: 'Seed topics' })).toBeDisabled()
  await user.click(screen.getByRole('button', { name: 'Seed topics' }))
  expect(topics.startSeed).not.toHaveBeenCalled()
})

it('surfaces a 409 from a concurrent run rather than doing nothing', async () => {
  const user = userEvent.setup()
  const topics = fakeTopics({
    startSeed: vi.fn().mockRejectedValue(new ApiError('a seed is already running', 409)),
  })
  const { stream } = fakeStream()

  renderWithContainer(<SeedPanel projectId={PROJECT} />, { topics, stream })

  const input = await screen.findByLabelText('Subject')
  await user.type(input, 'spaced repetition')
  await user.click(screen.getByRole('button', { name: 'Seed topics' }))

  await waitFor(() =>
    expect(useToasts.getState().toasts.at(-1)?.message).toBe('a seed is already running'),
  )
  // Refused, not silently accepted -- the control goes back to submittable.
  expect(screen.getByRole('button', { name: 'Seed topics' })).not.toBeDisabled()
})

it('shows a run already in flight on mount, from the catch-up route', async () => {
  const topics = fakeTopics({
    seedStatus: vi
      .fn()
      .mockResolvedValue({ current: run({ subject: 'memory consolidation' }), last: null }),
  })
  const { stream } = fakeStream()

  renderWithContainer(<SeedPanel projectId={PROJECT} />, { topics, stream })

  expect(await screen.findByText(/Naming topics for “memory consolidation”/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Seeding…' })).toBeDisabled()
})

it('says only that a run is in flight when catch-up has no subject for it', async () => {
  // A run this tab did not start itself -- picked up cold by `catchUp` --
  // has no locally-remembered subject to fall back to, and the running
  // frame itself never carries one. The honest thing to show is that a run
  // is happening, not a guess at what it is named for.
  const topics = fakeTopics({
    seedStatus: vi.fn().mockResolvedValue({ current: run({ subject: null }), last: null }),
  })
  const { stream } = fakeStream()

  renderWithContainer(<SeedPanel projectId={PROJECT} />, { topics, stream })

  expect(await screen.findByText('Naming topics…')).toBeInTheDocument()
})

it('shows the last run failing rather than staying silent about it', async () => {
  const topics = fakeTopics({
    seedStatus: vi.fn().mockResolvedValue({
      current: null,
      last: run({ status: 'failed', detail: 'the model refused' }),
    }),
  })
  const { stream } = fakeStream()

  renderWithContainer(<SeedPanel projectId={PROJECT} />, { topics, stream })

  const failed = await screen.findByText(/The last seed failed: the model refused/)
  // `data-failed` and not the colour class: the tone moved from `.seed-failed`
  // to a utility, and what this test is about is that the line is *marked* as
  // a failure at all, not which utility draws it.
  expect(failed).toHaveAttribute('data-failed', 'true')
})

it('updates from a live frame without waiting for a refetch', async () => {
  // The gap this closes: without this, a failed run looked exactly like a
  // hung one until the tab reloaded and hit the catch-up route.
  const topics = fakeTopics({
    seedStatus: vi
      .fn()
      .mockResolvedValue({ current: run({ subject: 'memory consolidation' }), last: null }),
  })
  const { stream, push } = fakeStream()

  renderWithContainer(<SeedPanel projectId={PROJECT} />, { topics, stream })
  await screen.findByText(/Naming topics for “memory consolidation”/)

  push(run({ status: 'failed', subject: 'memory consolidation', detail: 'the model refused' }))

  const failed = await screen.findByText(/The last seed failed: the model refused/)
  expect(failed).toHaveAttribute('data-failed', 'true')
  expect(topics.seedStatus).toHaveBeenCalledTimes(1)
})

it('refetches on reconnect, because a dropped frame cannot be replayed', async () => {
  const topics = fakeTopics()
  const { stream, reconnect } = fakeStream()

  renderWithContainer(<SeedPanel projectId={PROJECT} />, { topics, stream })
  await waitFor(() => expect(topics.seedStatus).toHaveBeenCalledTimes(1))

  reconnect()

  await waitFor(() => expect(topics.seedStatus).toHaveBeenCalledTimes(2))
})
