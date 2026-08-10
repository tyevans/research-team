import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { EventStreamListener, FeedFrame } from '@application/ports/event-stream.ts'
import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { EventIndex } from '@domain/session/event-index.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'
import type { Roster, Worker } from '@domain/worker/worker.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'

import { StreamProvider } from '../shell/StreamProvider.tsx'
import { AgentWidget } from './AgentWidget.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')
const OTHER = ProjectId('33333333-3333-3333-3333-333333333333')
const SESSION = SessionId('22222222-2222-2222-2222-222222222222')

const worker = (over: Partial<Worker> = {}): Worker => ({
  kind: 'turn',
  ref: SESSION,
  detail: 'turn 12',
  sessionId: SESSION,
  parent: null,
  startedAt: null,
  ...over,
})

const rosterOf = (projectId: ProjectId, workers: Worker[]): Roster => ({
  projectId,
  workers,
  idleSessionIds: [],
})

/** A stream a test can push frames into, standing in for the SSE connection. */
const fakeStream = () => {
  let listener: EventStreamListener | null = null
  return {
    stream: {
      connect: (l: EventStreamListener) => {
        listener = l
      },
      disconnect: () => {
        listener = null
      },
    },
    emit: (frame: FeedFrame) => listener?.onFrame(frame),
  }
}

const setup = (
  ui: ReactElement,
  parts: Partial<AppContainer> & { preferences?: InMemoryPreferenceStore },
) => {
  const container = {
    preferences: new InMemoryPreferenceStore(),
    projects: { list: vi.fn().mockResolvedValue([{ id: PROJECT, name: 'atlas' }]) },
    ...parts,
  } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <StreamProvider>{children}</StreamProvider>
      </ContainerProvider>
    </QueryClientProvider>
  )
  // `container` deliberately not re-exported: `render` already returns one
  // meaning the DOM node, and shadowing it with the fake container is how the
  // "draws nothing" test silently asserted against the wrong object.
  return { ...render(ui, { wrapper }), client }
}

const workersReturning = (rosters: Roster[]) => ({
  on: vi.fn(),
  everywhere: vi.fn().mockResolvedValue(rosters),
})

it('counts every worker across every project, not the projects', async () => {
  // "Actively running" is `Roster.workers` summed -- two projects working is
  // three agents when one of them has two. Counting rosters would say 2.
  const { stream } = fakeStream()
  setup(<AgentWidget />, {
    stream,
    workers: workersReturning([
      rosterOf(PROJECT, [worker(), worker({ ref: 'run-1', kind: 'run' })]),
      rosterOf(OTHER, [worker({ ref: 'src-1', kind: 'extraction', sessionId: null })]),
    ]),
  })

  expect(await screen.findByText('3 running')).toBeInTheDocument()
})

it('does not count a session that is merely attached', async () => {
  // `idleSessionIds` is a separate field precisely so this is a length rather
  // than a filter. Fails if the count ever starts reading it.
  const { stream } = fakeStream()
  setup(<AgentWidget />, {
    stream,
    workers: {
      on: vi.fn(),
      everywhere: vi
        .fn()
        .mockResolvedValue([{ projectId: PROJECT, workers: [], idleSessionIds: [SESSION] }]),
    },
  })

  expect(await screen.findByText('0 running')).toBeInTheDocument()
})

it('draws nothing at all when it is closed and nothing is running', async () => {
  // It is on every page, so an idle console must not pay any pixels for it.
  const preferences = new InMemoryPreferenceStore()
  preferences.setCollapsedPanes('agents', ['widget'])
  const { stream } = fakeStream()

  const { container } = setup(<AgentWidget />, {
    stream,
    preferences,
    workers: workersReturning([]),
  })

  await waitFor(() => expect(container.querySelector('.agents')).toBeNull())
})

it('stays on screen when it is open and nothing is running', async () => {
  // The other half of the rule above: a panel must not vanish under the
  // reader's cursor the moment the last agent finishes.
  const { stream } = fakeStream()
  setup(<AgentWidget />, { stream, workers: workersReturning([]) })

  expect(await screen.findByText(/nothing is running right now/i)).toBeInTheDocument()
})

it('names the toggle in words rather than a glyph', async () => {
  // `Pane.tsx` announces its toggles as "◂"/"▸", which is a known bug. This
  // fails if the accessible name is ever reduced to the dot.
  const { stream } = fakeStream()
  setup(<AgentWidget />, { stream, workers: workersReturning([rosterOf(PROJECT, [worker()])]) })

  expect(
    await screen.findByRole('button', { name: /1 running\. Hide what is running\./i }),
  ).toBeInTheDocument()
})

it('remembers that it was collapsed, the way every other pane is remembered', async () => {
  const preferences = new InMemoryPreferenceStore()
  const { stream } = fakeStream()
  setup(<AgentWidget />, {
    stream,
    preferences,
    workers: workersReturning([rosterOf(PROJECT, [worker()])]),
  })

  await userEvent.click(await screen.findByRole('button', { name: /Hide what is running/i }))

  expect(preferences.collapsedPanes('agents')).toEqual(['widget'])
})

it('opens collapsed when the preference says so', async () => {
  const preferences = new InMemoryPreferenceStore()
  preferences.setCollapsedPanes('agents', ['widget'])
  const { stream } = fakeStream()

  setup(<AgentWidget />, {
    stream,
    preferences,
    workers: workersReturning([rosterOf(PROJECT, [worker()])]),
  })

  expect(await screen.findByRole('button', { name: /Show what is running/i })).toBeInTheDocument()
  expect(screen.queryByRole('group', { name: /Agents running now/i })).toBeNull()
})

it('closes on Escape and gives focus back to the toggle', async () => {
  const { stream } = fakeStream()
  setup(<AgentWidget />, { stream, workers: workersReturning([rosterOf(PROJECT, [worker()])]) })

  await screen.findByRole('group', { name: /Agents running now/i })
  await userEvent.keyboard('{Escape}')

  const toggle = await screen.findByRole('button', { name: /Show what is running/i })
  expect(toggle).toHaveFocus()
})

it('shows the project name and what the agent last said, on the row', async () => {
  const { stream, emit } = fakeStream()
  setup(<AgentWidget />, { stream, workers: workersReturning([rosterOf(PROJECT, [worker()])]) })

  await screen.findByRole('group', { name: /Agents running now/i })
  emit({
    kind: 'log',
    sessionId: SESSION,
    entry: {
      index: EventIndex(4),
      type: 'AssistantMessageAdded',
      occurredAt: '2026-08-09T12:00:00Z',
      summary: 'checking the retention corpus',
      path: null,
      turnIndex: 1,
      isError: null,
      cancelled: null,
    },
  })

  // The sample comes off the frames the console already receives -- no request
  // is made for it. Fails if the row ever starts fetching a transcript.
  expect(await screen.findByText('checking the retention corpus')).toBeInTheDocument()
  expect(await screen.findByText('atlas')).toBeInTheDocument()
})

it('opens the agent’s feed when its row is clicked', async () => {
  const { stream } = fakeStream()
  setup(<AgentWidget />, {
    stream,
    workers: workersReturning([rosterOf(PROJECT, [worker()])]),
    // The drawer builds a real session store, so these are the reads it makes
    // on open. Cast because only that slice is exercised -- filling in the
    // rest of each port would be noise the test never touches.
    sessions: {
      read: vi.fn().mockResolvedValue(null),
      log: vi.fn().mockResolvedValue([]),
    } as unknown as AppContainer['sessions'],
    turns: {
      current: vi.fn().mockResolvedValue({ running: false }),
    } as unknown as AppContainer['turns'],
    approvals: {
      pending: vi.fn().mockResolvedValue([]),
    } as unknown as AppContainer['approvals'],
    now: () => 0,
  })

  await userEvent.click(await screen.findByRole('button', { name: /Open its feed/i }))

  // The drawer builds its own session store and subscribes to the log; all
  // this pins is that a row is the way in to one.
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
})

it('offers no feed for a worker that has no transcript', async () => {
  // An extraction's detail view is the extraction pane, not a session. A
  // button that opened an empty drawer would look live and do nothing.
  const { stream } = fakeStream()
  setup(<AgentWidget />, {
    stream,
    workers: workersReturning([
      rosterOf(PROJECT, [worker({ kind: 'extraction', ref: 'src-1', sessionId: null })]),
    ]),
  })

  await screen.findByRole('group', { name: /Agents running now/i })
  expect(screen.queryByRole('button', { name: /Open its feed/i })).toBeNull()
})

it('says it could not tell, rather than reporting zero, when the read fails', async () => {
  // A build with no roster wired 404s. Reporting "0 running" would be a
  // confident wrong answer that looks correct forever.
  const { stream } = fakeStream()
  setup(<AgentWidget />, {
    stream,
    workers: { on: vi.fn(), everywhere: vi.fn().mockRejectedValue(new Error('nope')) },
  })

  expect(await screen.findByText('agents unknown')).toBeInTheDocument()
})
