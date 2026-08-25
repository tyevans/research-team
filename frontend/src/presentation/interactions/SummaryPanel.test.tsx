import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { InteractionSummary } from '@domain/interaction/log.ts'

import { NO_INTERACTION_FILTERS, parseRoute } from '../routing/routes.ts'
import { SummaryPanel } from './SummaryPanel.tsx'

const summary = (over: Partial<InteractionSummary> = {}): InteractionSummary => ({
  byKind: [
    { kind: 'ViewEntered', count: 4102 },
    { kind: 'ActionUndone', count: 0 },
  ],
  byView: [
    {
      view: 'project/catalog',
      entries: 812,
      exits: 806,
      dwellMsMedian: 2310,
      dwellMsP90: 18_400,
      hiddenMsMedian: 0,
    },
  ],
  friction: {
    undone: 14,
    retried: 31,
    emptyResults: 96,
    emptyByWhere: [{ where: 'search', count: 61 }],
    repeatSearches: 22,
  },
  approvals: {
    total: 40,
    expanded: 12,
    medianLatencyMs: 3900,
    medianLatencyMsExpanded: 14_200,
    medianLatencyMsPlain: 900,
    byDecision: [{ decision: 'approved', count: 33 }],
  },
  ...over,
})

/** The filters a link would land on, read back through the parser that owns
 *  the grammar -- asserting on the query string itself would be asserting on
 *  the printer's spelling rather than on what the link means. */
const filtersOf = (link: HTMLElement) => {
  const route = parseRoute(link.getAttribute('href') ?? '')
  if (route.name !== 'interactions') throw new Error(`not an interactions link: ${route.name}`)
  return route.filters
}

describe('SummaryPanel', () => {
  it('renders a dwell median as a duration a person reads', () => {
    render(<SummaryPanel summary={summary()} filters={NO_INTERACTION_FILTERS} />)
    expect(screen.getByText('2.3s')).toBeInTheDocument()
    expect(screen.getByText('18.4s')).toBeInTheDocument()
  })

  it('renders an absent median as an em-dash and never as a zero', () => {
    render(
      <SummaryPanel
        filters={NO_INTERACTION_FILTERS}
        summary={summary({
          byView: [
            {
              view: 'interactions',
              entries: 3,
              exits: 0,
              dwellMsMedian: null,
              dwellMsP90: null,
              hiddenMsMedian: null,
            },
          ],
        })}
      />,
    )
    const row = screen.getByRole('row', { name: /interactions/ })
    expect(within(row).getAllByText('—')).toHaveLength(3)
    // A view with entries and no exits has no dwell. `0.0s` there would be a
    // claim that people left it instantly.
    expect(within(row).queryByText('0.0s')).not.toBeInTheDocument()
  })

  it('makes every kind count a link that applies itself as a filter', () => {
    render(<SummaryPanel summary={summary()} filters={NO_INTERACTION_FILTERS} />)
    expect(filtersOf(screen.getByRole('link', { name: /ViewEntered/ }))).toEqual({
      ...NO_INTERACTION_FILTERS,
      kinds: ['ViewEntered'],
    })
  })

  it('links a kind that has never been emitted, so the zero can be examined', () => {
    render(<SummaryPanel summary={summary()} filters={NO_INTERACTION_FILTERS} />)
    const link = screen.getByRole('link', { name: /ActionUndone 0/ })
    expect(filtersOf(link).kinds).toEqual(['ActionUndone'])
  })

  it('keeps the window a reader set up and replaces only the axes it names', () => {
    render(
      <SummaryPanel
        summary={summary()}
        filters={{
          ...NO_INTERACTION_FILTERS,
          since: '2026-08-01T00:00:00.000Z',
          installId: 'in-1',
          kinds: ['SearchPerformed'],
        }}
      />,
    )
    const filters = filtersOf(screen.getByRole('link', { name: /ViewEntered/ }))
    expect(filters.since).toBe('2026-08-01T00:00:00.000Z')
    expect(filters.installId).toBe('in-1')
    // Replaced, not added: clicking `ViewEntered` means "now show me these".
    expect(filters.kinds).toEqual(['ViewEntered'])
  })

  it('links a view row to both halves of its traffic, separately', () => {
    render(<SummaryPanel summary={summary()} filters={NO_INTERACTION_FILTERS} />)
    const row = screen.getByRole('row', { name: /project\/catalog/ })
    expect(filtersOf(within(row).getByRole('link', { name: '812' }))).toEqual({
      ...NO_INTERACTION_FILTERS,
      views: ['project/catalog'],
      kinds: ['ViewEntered'],
    })
    expect(filtersOf(within(row).getByRole('link', { name: '806' }))).toEqual({
      ...NO_INTERACTION_FILTERS,
      views: ['project/catalog'],
      kinds: ['ViewExited'],
    })
  })

  it('links each friction number to the kind that produces it', () => {
    render(<SummaryPanel summary={summary()} filters={NO_INTERACTION_FILTERS} />)
    expect(filtersOf(screen.getByRole('link', { name: /undone 14/ })).kinds).toEqual([
      'ActionUndone',
    ])
    expect(filtersOf(screen.getByRole('link', { name: /empty results 96/ })).kinds).toEqual([
      'EmptyResultEncountered',
    ])
  })

  it('says on screen that repeat searches are a heuristic', () => {
    render(<SummaryPanel summary={summary()} filters={NO_INTERACTION_FILTERS} />)
    expect(screen.getByText(/heuristic/)).toBeInTheDocument()
  })

  it('splits approval latency three ways and repeats the caveat on the count', () => {
    render(<SummaryPanel summary={summary()} filters={NO_INTERACTION_FILTERS} />)
    expect(
      screen.getByText(/median latency 3.9s — with details 14.2s, without 0.9s/),
    ).toBeInTheDocument()
    expect(screen.getByText(/floor on deliberation/)).toBeInTheDocument()
  })

  it('leaves a number no filter can express as plain text rather than a misleading link', () => {
    render(<SummaryPanel summary={summary()} filters={NO_INTERACTION_FILTERS} />)
    // `expanded_details` is not one of `/events`' filters. A link to every
    // approval would be a lie about what the reader asked for.
    expect(screen.queryByRole('link', { name: /details opened/ })).not.toBeInTheDocument()
    expect(screen.getByText(/details opened/)).toBeInTheDocument()
  })

  it('says a window has no views rather than drawing an empty table', () => {
    render(<SummaryPanel summary={summary({ byView: [] })} filters={NO_INTERACTION_FILTERS} />)
    expect(screen.getByText('No views in this window.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
