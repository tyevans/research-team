import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { InteractionLogRepository } from '@application/ports/repositories.ts'
import type {
  InteractionLogHealth,
  InteractionPage,
  InteractionSummary,
  LoggedInteraction,
} from '@domain/interaction/log.ts'
import { BrowserSessionId, InstallId } from '@domain/shared/identifier.ts'

import { InteractionsView } from './InteractionsView.tsx'

const SESSION = BrowserSessionId('3f2a11cc-0000-4000-8000-000000000001')

const health = (over: Partial<InteractionLogHealth> = {}): InteractionLogHealth => ({
  collecting: true,
  total: 3,
  firstAt: new Date('2026-08-25T09:00:00Z'),
  lastAt: new Date('2026-08-25T10:00:00Z'),
  kinds: [{ kind: 'ViewEntered', count: 3 }],
  failures: [],
  installCount: 1,
  sessionCount: 1,
  ...over,
})

const summary = (over: Partial<InteractionSummary> = {}): InteractionSummary => ({
  byKind: [{ kind: 'ViewExited', count: 2 }],
  byView: [
    {
      view: 'project/catalog',
      entries: 3,
      exits: 2,
      dwellMsMedian: 2310,
      dwellMsP90: 4000,
      hiddenMsMedian: null,
    },
  ],
  friction: { undone: 0, retried: 0, emptyResults: 0, emptyByWhere: [], repeatSearches: 0 },
  approvals: {
    total: 0,
    expanded: 0,
    medianLatencyMs: null,
    medianLatencyMsExpanded: null,
    medianLatencyMsPlain: null,
    byDecision: [],
  },
  ...over,
})

const anEvent = (over: Partial<LoggedInteraction> = {}): LoggedInteraction => ({
  browserSessionId: SESSION,
  installId: InstallId('in-1'),
  seq: 1,
  kind: 'ViewExited',
  view: 'project/catalog',
  occurredAt: new Date('2026-08-25T10:00:00Z'),
  receivedAt: null,
  projectId: null,
  sessionId: null,
  payload: { dwell_ms: 2310, hidden_ms: 0 },
  ...over,
})

const aPage = (events: readonly LoggedInteraction[], total = events.length): InteractionPage => ({
  events,
  total,
  limit: 200,
  offset: 0,
})

/** Throws until stubbed, matching this directory's other fakes: a pane that
 *  reaches for something it did not mean to fails loudly rather than resolving
 *  `undefined` and rendering an empty state that looks correct. */
const fakeLog = (over: Partial<InteractionLogRepository> = {}): InteractionLogRepository => ({
  health: vi.fn<InteractionLogRepository['health']>().mockResolvedValue(health()),
  summary: vi.fn<InteractionLogRepository['summary']>().mockResolvedValue(summary()),
  events: vi.fn<InteractionLogRepository['events']>().mockResolvedValue(aPage([anEvent()])),
  sessions: vi.fn(() => {
    throw new Error('sessions was not stubbed for this test')
  }),
  session: vi.fn(() => {
    throw new Error('session was not stubbed for this test')
  }),
  ...over,
})

const show = (log: InteractionLogRepository): ReactElement => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <ContainerProvider container={{ interactionLog: log } as unknown as AppContainer}>
        <InteractionsView />
      </ContainerProvider>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  window.location.hash = '#/i'
})

describe('InteractionsView', () => {
  it('renders the four regions in the order the questions are asked', async () => {
    render(show(fakeLog()))
    await screen.findByRole('region', { name: 'Log health' })
    const regions = screen.getAllByRole('region').map((region) => region.getAttribute('aria-label'))
    expect(regions).toEqual(['Log health', 'Filters', 'Summary', 'Events'])
  })

  it('renders a rendered number rather than reporting that a fetch happened', async () => {
    render(show(fakeLog()))
    expect(await screen.findByText('2.3s')).toBeInTheDocument()
  })

  it('reads its filters from the route', async () => {
    window.location.hash = '#/i?kind=ViewExited&install=in-1'
    render(show(fakeLog()))
    await waitFor(() => {
      expect(screen.getByRole('checkbox', { name: 'ViewExited' })).toBeChecked()
    })
    expect(screen.getByLabelText('install')).toHaveValue('in-1')
  })

  it('writes a filter change back to the route, which is what makes it linkable', async () => {
    render(show(fakeLog()))
    await screen.findByRole('checkbox', { name: 'SearchPerformed' })
    await userEvent.click(screen.getByRole('checkbox', { name: 'SearchPerformed' }))
    await waitFor(() => {
      expect(window.location.hash).toBe('#/i?kind=SearchPerformed')
    })
  })

  it('narrows the feed when a summary count is clicked', async () => {
    render(show(fakeLog()))
    const link = await screen.findByRole('link', { name: /ViewExited 2/ })
    await userEvent.click(link)
    await waitFor(() => {
      expect(window.location.hash).toBe('#/i?kind=ViewExited')
    })
    await waitFor(() => {
      expect(screen.getByRole('checkbox', { name: 'ViewExited' })).toBeChecked()
    })
  })

  it('swaps the feed for one browser session when the route names one', async () => {
    window.location.hash = `#/i?session=${SESSION}`
    const events = vi.fn<InteractionLogRepository['events']>().mockResolvedValue(aPage([]))
    render(
      show(
        fakeLog({
          events,
          session: vi
            .fn<InteractionLogRepository['session']>()
            .mockResolvedValue([
              anEvent({ seq: 1, kind: 'ViewEntered', payload: {} }),
              anEvent({ seq: 2, occurredAt: new Date('2026-08-25T10:00:02.300Z') }),
            ]),
        }),
      ),
    )
    await screen.findByRole('region', { name: 'Browser session' })
    // Ascending, with the gap -- the only order a visit reads as a story in.
    expect(await screen.findByText('+2.3s')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Events' })).not.toBeInTheDocument()
    // And the paged feed is not fetched at all while a session is on screen.
    expect(events).not.toHaveBeenCalled()
  })

  it('leaves the drill-down for the whole log again', async () => {
    window.location.hash = `#/i?session=${SESSION}`
    render(
      show(
        fakeLog({
          session: vi.fn<InteractionLogRepository['session']>().mockResolvedValue([anEvent()]),
        }),
      ),
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Back to all events' }))
    await waitFor(() => {
      expect(window.location.hash).toBe('#/i')
    })
    await screen.findByRole('region', { name: 'Events' })
  })

  it('tells a reader how much of the filtered set is on screen', async () => {
    render(
      show(
        fakeLog({
          events: vi
            .fn<InteractionLogRepository['events']>()
            .mockResolvedValue(aPage([anEvent()], 9000)),
        }),
      ),
    )
    // 1-of-9000 rather than a page length: a reader who cannot tell that from
    // 1-of-1 cannot tell a filter that found everything from one that capped.
    expect(await screen.findByText(/1 of 9000, newest first/)).toBeInTheDocument()
  })

  it('makes a failed read visible rather than drawing it as an idle user', async () => {
    render(
      show(
        fakeLog({
          events: vi
            .fn<InteractionLogRepository['events']>()
            .mockRejectedValue(new Error('read models are not available')),
        }),
      ),
    )
    expect(await screen.findByText('The events could not be read.')).toBeInTheDocument()
    expect(screen.getByText(/read models are not available/)).toBeInTheDocument()
    // The empty state must not be what a broken instrument looks like.
    expect(screen.queryByText('No events under this filter.')).not.toBeInTheDocument()
  })

  it('renders an empty log as a state with a message, not as a blank page', async () => {
    render(
      show(
        fakeLog({
          health: vi
            .fn<InteractionLogRepository['health']>()
            .mockResolvedValue(health({ total: 0, firstAt: null, lastAt: null, sessionCount: 0 })),
          events: vi.fn<InteractionLogRepository['events']>().mockResolvedValue(aPage([])),
        }),
      ),
    )
    expect(await screen.findByText('No events under this filter.')).toBeInTheDocument()
    expect(screen.getByText('never')).toBeInTheDocument()
  })
})
