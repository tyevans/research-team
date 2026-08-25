import { describe, expect, it, vi } from 'vitest'

import type { InteractionFilters } from '@domain/interaction/filters.ts'
import { NO_FILTERS } from '@domain/interaction/filters.ts'
import { BrowserSessionId } from '@domain/shared/identifier.ts'

import type { HttpClient } from './http-client.ts'
import { HttpInteractionLogRepository } from './interaction-log-query-repository.ts'

/** Enough of a response for the schema to accept, per route. The repository's
 *  job under test is the *request*, so these are the minimum that gets past
 *  validation -- a fuller body would only make the assertion below harder to
 *  read. */
const EMPTY_PAGE = { events: [], total: 0, limit: 200, offset: 0 }
const EMPTY_SESSIONS = { sessions: [], total: 0 }
const EMPTY_SUMMARY = {
  by_kind: {},
  by_view: [],
  friction: { undone: 0, retried: 0, empty_results: 0, empty_by_where: [], repeat_searches: 0 },
  approvals: {
    total: 0,
    expanded: 0,
    median_latency_ms: null,
    median_latency_ms_expanded: null,
    median_latency_ms_plain: null,
    by_decision: {},
  },
}

const repositoryOver = (response: unknown) => {
  const get = vi.fn().mockResolvedValue(response)
  return { get, repository: new HttpInteractionLogRepository({ get } as unknown as HttpClient) }
}

const urlOf = (get: ReturnType<typeof vi.fn>): string => get.mock.calls[0]?.[0] as string

describe('HttpInteractionLogRepository query strings', () => {
  /** The exact place a client and a server disagree with neither failing.
   *
   * FastAPI reads a repeatable parameter as `?kind=A&kind=B`. A comma-joined
   * `?kind=A,B` arrives as a single string named `A,B`, matches no kind in the
   * vocabulary, and answers an empty feed -- which is indistinguishable from a
   * window in which nothing happened. Nothing raises on either side. */
  it('repeats the kind key rather than joining the kinds', async () => {
    const { get, repository } = repositoryOver(EMPTY_PAGE)

    await repository.events({ ...NO_FILTERS, kinds: ['ViewEntered', 'SearchPerformed'] })

    expect(urlOf(get)).toBe('/api/interactions/events?kind=ViewEntered&kind=SearchPerformed')
    // Spelled out as a second assertion rather than trusted to the string
    // above, because the failure this guards is a comma and a comma is one
    // character to miss in a long URL.
    expect(urlOf(get)).not.toContain('ViewEntered,SearchPerformed')
  })

  it('repeats the view key rather than joining the views', async () => {
    const { get, repository } = repositoryOver(EMPTY_PAGE)

    await repository.events({ ...NO_FILTERS, views: ['project/catalog', 'home'] })

    expect(urlOf(get)).toBe('/api/interactions/events?view=project%2Fcatalog&view=home')
  })

  it('round-trips a filter with every field set', async () => {
    const filters: InteractionFilters = {
      kinds: ['ViewEntered', 'ViewExited'],
      views: ['home'],
      projectId: '11111111-1111-4111-8111-111111111111',
      installId: '22222222-2222-4222-8222-222222222222',
      browserSessionId: '33333333-3333-4333-8333-333333333333',
      since: '2026-08-01T00:00:00Z',
      until: '2026-08-25T00:00:00Z',
    }
    const { get, repository } = repositoryOver(EMPTY_PAGE)

    await repository.events(filters, { limit: 50, offset: 100, order: 'oldest' })

    // Parsed back rather than compared as a string: the assertion is that
    // every field arrived under the name the route expects, and pinning the
    // encoder's ordering as well would fail on a change that broke nothing.
    const parsed = new URLSearchParams(urlOf(get).split('?')[1])
    expect(parsed.getAll('kind')).toEqual(['ViewEntered', 'ViewExited'])
    expect(parsed.getAll('view')).toEqual(['home'])
    expect(parsed.get('project_id')).toBe(filters.projectId)
    expect(parsed.get('install_id')).toBe(filters.installId)
    expect(parsed.get('browser_session_id')).toBe(filters.browserSessionId)
    expect(parsed.get('since')).toBe(filters.since)
    expect(parsed.get('until')).toBe(filters.until)
    expect(parsed.get('limit')).toBe('50')
    expect(parsed.get('offset')).toBe('100')
    expect(parsed.get('order')).toBe('oldest')
  })

  it('asks bare when nothing is filtered or windowed', async () => {
    const { get, repository } = repositoryOver(EMPTY_PAGE)

    await repository.events(NO_FILTERS)

    // No trailing `?`, and no limit at the server's own default: an unwindowed
    // request is byte-identical to what the bare route would have been.
    expect(urlOf(get)).toBe('/api/interactions/events')
  })

  /** `/sessions` accepts install, project and the time window and nothing
   *  else. A parameter the server does not know is ignored silently, so
   *  sending `kind` here would answer the *unfiltered* list under a narrowed
   *  filter bar -- a wrong answer with no error anywhere. */
  it('drops the axes the sessions route does not understand', async () => {
    const { get, repository } = repositoryOver(EMPTY_SESSIONS)

    await repository.sessions(
      {
        ...NO_FILTERS,
        kinds: ['ViewEntered'],
        views: ['home'],
        browserSessionId: '33333333-3333-4333-8333-333333333333',
        installId: '22222222-2222-4222-8222-222222222222',
        since: '2026-08-01T00:00:00Z',
      },
      { limit: 10, order: 'oldest' },
    )

    const parsed = new URLSearchParams(urlOf(get).split('?')[1])
    expect(parsed.getAll('kind')).toEqual([])
    expect(parsed.getAll('view')).toEqual([])
    expect(parsed.get('browser_session_id')).toBeNull()
    // The route is newest-first and takes no ordering.
    expect(parsed.get('order')).toBeNull()
    expect(parsed.get('install_id')).toBe('22222222-2222-4222-8222-222222222222')
    expect(parsed.get('since')).toBe('2026-08-01T00:00:00Z')
    expect(parsed.get('limit')).toBe('10')
  })

  it('reads one session by a path segment, not a filter', async () => {
    const { get, repository } = repositoryOver({ events: [] })

    await repository.session(BrowserSessionId('33333333-3333-4333-8333-333333333333'))

    expect(urlOf(get)).toBe('/api/interactions/sessions/33333333-3333-4333-8333-333333333333')
  })

  it('asks for health unfiltered', async () => {
    const { get, repository } = repositoryOver({
      collecting: true,
      total: 0,
      first_at: null,
      last_at: null,
      kinds: {},
      failures: [],
      install_count: 0,
      session_count: 0,
    })

    await repository.health()

    expect(urlOf(get)).toBe('/api/interactions/health')
  })

  it('summarises over the filter and never over a page', async () => {
    const { get, repository } = repositoryOver(EMPTY_SUMMARY)

    await repository.summary({ ...NO_FILTERS, kinds: ['ApprovalDecided'], views: ['home'] })

    // A summary of a page rather than of the filtered set would be a number
    // that changed as somebody scrolled the feed under it.
    const parsed = new URLSearchParams(urlOf(get).split('?')[1])
    expect(parsed.getAll('kind')).toEqual(['ApprovalDecided'])
    expect(parsed.get('limit')).toBeNull()
    expect(parsed.get('offset')).toBeNull()
  })
})

describe('HttpInteractionLogRepository responses', () => {
  it('hands back domain values, not the wire shape', async () => {
    const { repository } = repositoryOver({
      events: [
        {
          browser_session_id: '33333333-3333-4333-8333-333333333333',
          install_id: '22222222-2222-4222-8222-222222222222',
          seq: 7,
          kind: 'ViewExited',
          view: 'project/catalog',
          occurred_at: '2026-08-25T14:51:22Z',
          received_at: null,
          project_id: '11111111-1111-4111-8111-111111111111',
          session_id: null,
          payload: { dwell_ms: 2310 },
        },
      ],
      total: 9000,
      limit: 200,
      offset: 0,
    })

    const page = await repository.events(NO_FILTERS)

    // `total` and not `page.events.length`: the whole reason the route sends
    // both is that a reader who cannot tell 1-of-1 from 1-of-9000 cannot tell
    // a filter that found everything from one that hit the cap.
    expect(page.total).toBe(9000)
    expect(page.events[0]?.occurredAt.toISOString()).toBe('2026-08-25T14:51:22.000Z')
    expect(page.events[0]?.receivedAt).toBeNull()
    expect(page.events[0]?.payload).toEqual({ dwell_ms: 2310 })
  })

  it('unpages the whole stream of one session', async () => {
    const { repository } = repositoryOver({
      events: [
        {
          browser_session_id: '33333333-3333-4333-8333-333333333333',
          install_id: '22222222-2222-4222-8222-222222222222',
          seq: 1,
          kind: 'ViewEntered',
          view: 'home',
          occurred_at: '2026-08-25T14:00:00Z',
          payload: {},
        },
      ],
    })

    const stream = await repository.session(
      BrowserSessionId('33333333-3333-4333-8333-333333333333'),
    )

    expect(stream.map((event) => event.seq)).toEqual([1])
    expect(stream[0]?.view).toBe('home')
  })
})
