import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { LoggedInteraction } from '@domain/interaction/log.ts'
import { BrowserSessionId, InstallId, ProjectId } from '@domain/shared/identifier.ts'

import { NO_INTERACTION_FILTERS, parseRoute } from '../routing/routes.ts'
import { InteractionFeed } from './InteractionFeed.tsx'

const SESSION = BrowserSessionId('3f2a11cc-0000-4000-8000-000000000001')

const anEvent = (over: Partial<LoggedInteraction> = {}): LoggedInteraction => ({
  browserSessionId: SESSION,
  installId: InstallId('in-1'),
  seq: 1,
  kind: 'ViewEntered',
  view: 'project/catalog',
  occurredAt: new Date('2026-08-25T10:00:00Z'),
  receivedAt: null,
  projectId: null,
  sessionId: null,
  payload: {},
  ...over,
})

describe('InteractionFeed', () => {
  it('renders one row per event, with the payload as prose', () => {
    render(
      <InteractionFeed
        order="newest"
        filters={NO_INTERACTION_FILTERS}
        events={[
          anEvent({ seq: 2, kind: 'ViewExited', payload: { dwell_ms: 2310, hidden_ms: 400 } }),
          anEvent({ seq: 1 }),
        ]}
      />,
    )
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText('left project/catalog after 2.3s (0.4s hidden)')).toBeInTheDocument()
  })

  it('keeps the raw payload behind a disclosure rather than on the row', async () => {
    render(
      <InteractionFeed
        order="newest"
        filters={NO_INTERACTION_FILTERS}
        events={[
          anEvent({
            kind: 'SearchPerformed',
            payload: { query_text: 'aqueducts', result_count: 0 },
          }),
        ]}
      />,
    )
    expect(screen.queryByText(/"query_text"/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'raw' }))
    expect(screen.getByText(/"query_text": "aqueducts"/)).toBeInTheDocument()
  })

  it('links a row to its browser session, dropping the axes a visit should not inherit', () => {
    render(
      <InteractionFeed
        order="newest"
        filters={{ ...NO_INTERACTION_FILTERS, kinds: ['ViewEntered'], installId: 'in-1' }}
        events={[anEvent()]}
      />,
    )
    const route = parseRoute(screen.getByRole('link').getAttribute('href') ?? '')
    if (route.name !== 'interactions') throw new Error('not an interactions link')
    expect(route.filters.browserSessionId).toBe(SESSION)
    // A drill-down is one visit end to end; a kind filter carried into it
    // would hide most of the story.
    expect(route.filters.kinds).toEqual([])
    expect(route.filters.installId).toBe('in-1')
  })

  it('shows the gap between consecutive events when the order is a story', () => {
    render(
      <InteractionFeed
        order="ascending"
        filters={NO_INTERACTION_FILTERS}
        events={[
          anEvent({ seq: 1, occurredAt: new Date('2026-08-25T10:00:00Z') }),
          anEvent({ seq: 2, occurredAt: new Date('2026-08-25T10:00:02.300Z') }),
        ]}
      />,
    )
    expect(screen.getByText('+2.3s')).toBeInTheDocument()
    // Never on the first row: there is nothing before it.
    const [first] = screen.getAllByRole('listitem')
    expect(within(first as HTMLElement).queryByText(/^\+/)).not.toBeInTheDocument()
  })

  it('shows no gaps in the newest-first feed, where the two rows are unrelated visits', () => {
    render(
      <InteractionFeed
        order="newest"
        filters={NO_INTERACTION_FILTERS}
        events={[
          anEvent({ seq: 2, occurredAt: new Date('2026-08-25T10:00:02.300Z') }),
          anEvent({ seq: 1, occurredAt: new Date('2026-08-25T10:00:00Z') }),
        ]}
      />,
    )
    expect(screen.queryByText('+2.3s')).not.toBeInTheDocument()
  })

  it('marks the date where it changes, and only there', () => {
    render(
      <InteractionFeed
        order="ascending"
        filters={NO_INTERACTION_FILTERS}
        events={[
          anEvent({ seq: 1, occurredAt: new Date('2026-08-24T23:59:00Z') }),
          anEvent({ seq: 2, occurredAt: new Date('2026-08-25T00:01:00Z') }),
          anEvent({ seq: 3, occurredAt: new Date('2026-08-25T00:02:00Z') }),
        ]}
      />,
    )
    // Two rows a minute apart across midnight are otherwise two clock times
    // that look an hour apart, and there is no hover to disambiguate them --
    // `title` reaches a mouse and no other reader.
    expect(screen.getAllByText(/2026-08-24/)).toHaveLength(1)
    expect(screen.getAllByText(/2026-08-25/)).toHaveLength(1)
  })

  it('names both readings of an empty feed rather than drawing a blank page', () => {
    render(<InteractionFeed order="newest" filters={NO_INTERACTION_FILTERS} events={[]} />)
    expect(screen.getByText('No events under this filter.')).toBeInTheDocument()
    expect(screen.getByText(/nothing has been recorded/)).toBeInTheDocument()
  })

  it('names the ids a row is about when it has them', () => {
    render(
      <InteractionFeed
        order="newest"
        filters={NO_INTERACTION_FILTERS}
        events={[anEvent({ projectId: ProjectId('9c1d0000-0000-4000-8000-000000000002') })]}
      />,
    )
    expect(screen.getByText(/project 9c1d0000…/)).toBeInTheDocument()
    expect(screen.getByText('seq 1')).toBeInTheDocument()
  })
})
