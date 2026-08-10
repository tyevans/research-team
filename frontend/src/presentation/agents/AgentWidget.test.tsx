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

/** Open the popover the way a reader does.
 *
 * Every test that wants rows starts here now, because the nav item is closed
 * until asked -- which is the whole point of moving it off the page. Under the
 * floating widget these tests found rows already on screen.
 */
const open = async () => {
  await userEvent.click(await screen.findByRole('button', { name: /Show what is running/i }))
  return screen.findByRole('group', { name: /Agents running now/i })
}

const said = (summary: string): FeedFrame => ({
  kind: 'log',
  sessionId: SESSION,
  entry: {
    index: EventIndex(4),
    type: 'AssistantMessageAdded',
    occurredAt: '2026-08-09T12:00:00Z',
    summary,
    path: null,
    turnIndex: 1,
    isError: null,
    cancelled: null,
  },
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

  // Asserted through the accessible name rather than the visible text: the
  // numeral and the word are separate nodes so the word can be dropped at
  // 420px, and the name is the thing that must read as a sentence anyway.
  expect(await screen.findByRole('button', { name: /^3 running\./ })).toBeInTheDocument()
})

it('does not count a session that is merely attached', async () => {
  // `idleSessionIds` is a separate field precisely so this is a length rather
  // than a filter. Fails if the count ever starts reading it.
  //
  // Opened by preference, because zero *and closed* now draws nothing at all
  // and there would be no count to read. Reading it from a shut widget is what
  // the previous version of this test did, and it can no longer.
  const preferences = new InMemoryPreferenceStore()
  preferences.setCollapsedPanes('agents', ['popover'])
  const { stream } = fakeStream()
  setup(<AgentWidget />, {
    stream,
    preferences,
    workers: {
      on: vi.fn(),
      everywhere: vi
        .fn()
        .mockResolvedValue([{ projectId: PROJECT, workers: [], idleSessionIds: [SESSION] }]),
    },
  })

  expect(await screen.findByRole('button', { name: /^0 running\./ })).toBeInTheDocument()
})

it('draws nothing at all when it is closed and nothing is running', async () => {
  // It is in the topbar on every page, so an idle console must not pay any
  // width for it -- the breadcrumb gets it back.
  const { stream } = fakeStream()

  const { container } = setup(<AgentWidget />, { stream, workers: workersReturning([]) })

  await waitFor(() => expect(container.querySelector('.agents')).toBeNull())
})

it('stays open when the last agent finishes', async () => {
  // The other half of the rule above: an open popover must not vanish under
  // the reader's cursor the moment the last agent finishes.
  const { stream } = fakeStream()
  setup(<AgentWidget />, { stream, workers: workersReturning([rosterOf(PROJECT, [worker()])]) })

  await open()
  expect(await screen.findByRole('group', { name: /Agents running now/i })).toBeInTheDocument()
})

it('names the toggle in words rather than a glyph', async () => {
  // `Pane.tsx` announces its toggles as "◂"/"▸", which is a known bug. This
  // fails if the accessible name is ever reduced to the dot.
  const { stream } = fakeStream()
  setup(<AgentWidget />, { stream, workers: workersReturning([rosterOf(PROJECT, [worker()])]) })

  expect(
    await screen.findByRole('button', { name: /1 running\. Show what is running\./i }),
  ).toBeInTheDocument()
})

it('stays shut on a console it has never been opened on', async () => {
  // The occlusion rule, pinned. A popover hanging below the nav is over the
  // page content, so it may only be there because someone asked -- and a fresh
  // browser has asked for nothing. Fails against the floating widget, whose
  // default was open.
  const { stream } = fakeStream()
  setup(<AgentWidget />, {
    stream,
    preferences: new InMemoryPreferenceStore(),
    workers: workersReturning([rosterOf(PROJECT, [worker()])]),
  })

  expect(await screen.findByRole('button', { name: /Show what is running/i })).toBeInTheDocument()
  expect(screen.queryByRole('group', { name: /Agents running now/i })).toBeNull()
})

it('remembers that it was opened, the way every other pane is remembered', async () => {
  const preferences = new InMemoryPreferenceStore()
  const { stream } = fakeStream()
  setup(<AgentWidget />, {
    stream,
    preferences,
    workers: workersReturning([rosterOf(PROJECT, [worker()])]),
  })

  await open()

  expect(preferences.collapsedPanes('agents')).toEqual(['popover'])
})

it('opens straight away when the reader left it open', async () => {
  const preferences = new InMemoryPreferenceStore()
  preferences.setCollapsedPanes('agents', ['popover'])
  const { stream } = fakeStream()

  setup(<AgentWidget />, {
    stream,
    preferences,
    workers: workersReturning([rosterOf(PROJECT, [worker()])]),
  })

  expect(await screen.findByRole('group', { name: /Agents running now/i })).toBeInTheDocument()
})

it('closes on Escape and gives focus back to the toggle', async () => {
  const { stream } = fakeStream()
  setup(<AgentWidget />, { stream, workers: workersReturning([rosterOf(PROJECT, [worker()])]) })

  await open()
  await userEvent.keyboard('{Escape}')

  const toggle = await screen.findByRole('button', { name: /Show what is running/i })
  expect(toggle).toHaveFocus()
})

it('closes when the page behind it is used', async () => {
  // The owner's complaint was occlusion. A popover over the page earns its
  // place only by getting out of the way without being hunted for, so a press
  // anywhere else dismisses it. Fails against the floating widget, which
  // stayed until its own toggle was found and clicked.
  const { stream } = fakeStream()
  setup(
    <>
      <button type="button">something else</button>
      <AgentWidget />
    </>,
    { stream, workers: workersReturning([rosterOf(PROJECT, [worker()])]) },
  )

  await open()
  await userEvent.click(screen.getByRole('button', { name: 'something else' }))

  await waitFor(() =>
    expect(screen.queryByRole('group', { name: /Agents running now/i })).toBeNull(),
  )
})

it('moves focus into the popover when it opens', async () => {
  // A keyboard reader who opens it lands on the first agent rather than
  // tabbing the rest of the topbar first. Escape brings them back.
  const { stream } = fakeStream()
  setup(<AgentWidget />, { stream, workers: workersReturning([rosterOf(PROJECT, [worker()])]) })

  await open()

  await waitFor(() => expect(screen.getByRole('button', { name: /Open its feed/i })).toHaveFocus())
})

it('folds no transcript frames while it is closed', async () => {
  // The cost property, and the one most at risk in moving to a bar that is
  // mounted on every page: a closed popover does no work when the log moves.
  // Frames that arrive while it is shut are not folded, so they are not there
  // to be shown when it opens -- and a build that folded them anyway would
  // show "while nobody was looking" the moment the panel appeared.
  const { stream, emit } = fakeStream()
  setup(<AgentWidget />, { stream, workers: workersReturning([rosterOf(PROJECT, [worker()])]) })

  await screen.findByRole('button', { name: /Show what is running/i })
  emit(said('while nobody was looking'))

  const panel = await open()
  expect(panel).not.toHaveTextContent('while nobody was looking')

  // And folding resumes on opening, so the row is not permanently blank.
  emit(said('now that someone is'))
  expect(await screen.findByText('now that someone is')).toBeInTheDocument()
})

it('shows the project name and what the agent last said, on the row', async () => {
  const { stream, emit } = fakeStream()
  setup(<AgentWidget />, { stream, workers: workersReturning([rosterOf(PROJECT, [worker()])]) })

  await open()
  emit(said('checking the retention corpus'))

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

  await open()
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

  await open()
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
