import { describe, expect, it } from 'vitest'

import * as dto from './dto.ts'
import {
  toApprovalSummary,
  toBrowserSession,
  toBrowserSessionPage,
  toInteractionLogHealth,
  toInteractionSummary,
  toLoggedInteraction,
  toProjectionFailure,
  toViewDwell,
} from './mappers.ts'

/** Every mapper is driven through its schema rather than from a hand-written
 *  object, so a field the DTO defaults or transforms is exercised the way a
 *  real response would exercise it. A literal passed straight to the mapper
 *  would skip the schema entirely, which is where `maybe()` and the `instant`
 *  refinement live. */
const parsed = <S extends { parse: (raw: unknown) => unknown }>(schema: S, raw: unknown) =>
  schema.parse(raw) as never

const SESSION = '33333333-3333-4333-8333-333333333333'
const INSTALL = '22222222-2222-4222-8222-222222222222'
const PROJECT = '11111111-1111-4111-8111-111111111111'

describe('toInteractionLogHealth', () => {
  it('reads an empty log as collecting with no first or last instant', () => {
    // The real state of a fresh install, and of one where collection is on and
    // nothing has been done yet. `null` rather than a substituted instant:
    // there is no honest date to show, and any placeholder renders as a real
    // one.
    const health = toInteractionLogHealth(
      parsed(dto.interactionHealthDto, {
        collecting: true,
        total: 0,
        first_at: null,
        last_at: null,
        kinds: { ViewEntered: 0, ViewExited: 0 },
        failures: [],
        install_count: 0,
        session_count: 0,
      }),
    )

    expect(health.firstAt).toBeNull()
    expect(health.lastAt).toBeNull()
    expect(health.total).toBe(0)
    // The zeros survive. A kind that was never emitted and a kind that does
    // not exist must not look the same, which is the whole reason the server
    // sends the vocabulary rather than what the table happens to hold.
    expect(health.kinds).toEqual([
      { kind: 'ViewEntered', count: 0 },
      { kind: 'ViewExited', count: 0 },
    ])
  })

  it('keeps the vocabulary order the server sent rather than sorting', () => {
    const health = toInteractionLogHealth(
      parsed(dto.interactionHealthDto, {
        collecting: false,
        total: 3,
        first_at: '2026-08-19T09:12:04Z',
        last_at: '2026-08-25T14:51:22Z',
        // Deliberately neither alphabetical nor descending by count: either
        // ordering imposed here would pass a sorted assertion by accident.
        kinds: { ViewEntered: 2, AttentionLost: 0, SearchPerformed: 1 },
        failures: [],
        install_count: 1,
        session_count: 1,
      }),
    )

    expect(health.kinds.map((entry) => entry.kind)).toEqual([
      'ViewEntered',
      'AttentionLost',
      'SearchPerformed',
    ])
    expect(health.collecting).toBe(false)
    expect(health.firstAt?.toISOString()).toBe('2026-08-19T09:12:04.000Z')
  })

  it('carries a dead-lettered event through with its instant parsed', () => {
    const failure = toProjectionFailure(
      parsed(dto.interactionFailureDto, {
        // A number, which is what `DLQEntry.id` is on some backends. The
        // schema stringifies it: a key rendered as `[object Object]` or
        // compared against a string id would be a row that never matched.
        id: 41,
        event_type: 'InteractionReported',
        error: 'no projection accepted it',
        failed_at: '2026-08-25T14:00:00Z',
      }),
    )

    expect(failure.id).toBe('41')
    expect(failure.failedAt?.toISOString()).toBe('2026-08-25T14:00:00.000Z')
  })

  it('reads a failure with no recorded instant as null', () => {
    const failure = toProjectionFailure(
      parsed(dto.interactionFailureDto, { id: 'a', event_type: 'X', error: 'e', failed_at: null }),
    )

    expect(failure.failedAt).toBeNull()
  })
})

describe('toLoggedInteraction', () => {
  it('brands the ids and parses the instants', () => {
    const event = toLoggedInteraction(
      parsed(dto.interactionEventDto, {
        browser_session_id: SESSION,
        install_id: INSTALL,
        seq: 12,
        kind: 'ViewExited',
        view: 'project/catalog',
        occurred_at: '2026-08-25T14:51:22Z',
        received_at: '2026-08-25T14:51:23Z',
        project_id: PROJECT,
        session_id: null,
        payload: { dwell_ms: 2310, hidden_ms: 400 },
      }),
    )

    expect(event.browserSessionId).toBe(SESSION)
    expect(event.installId).toBe(INSTALL)
    expect(event.projectId).toBe(PROJECT)
    // Null and not the empty string: no domain session was involved, and an
    // empty id would be a link to nowhere rather than an absent link.
    expect(event.sessionId).toBeNull()
    // The lag between the two is what the drill-down subtracts, which is why
    // both are `Date`s and neither is a string.
    expect(event.receivedAt!.getTime() - event.occurredAt.getTime()).toBe(1000)
    // Untouched, and deliberately: the shape differs per kind, and renaming
    // fifteen payloads here would put the vocabulary in two places.
    expect(event.payload).toEqual({ dwell_ms: 2310, hidden_ms: 400 })
  })

  it('reads an absent received_at as null rather than defaulting it', () => {
    // A row written before the column existed. Substituting `occurred_at`
    // would report a delivery lag of exactly zero, which is a measurement
    // nobody took.
    const event = toLoggedInteraction(
      parsed(dto.interactionEventDto, {
        browser_session_id: SESSION,
        install_id: INSTALL,
        seq: 1,
        kind: 'ViewEntered',
        view: 'home',
        occurred_at: '2026-08-25T14:00:00Z',
      }),
    )

    expect(event.receivedAt).toBeNull()
    expect(event.projectId).toBeNull()
    expect(event.payload).toEqual({})
  })

  it('refuses an instant it cannot parse, naming the field', () => {
    // Without the refinement in `dto.ts` this would map to an `Invalid Date`,
    // render as the literal text "Invalid Date", and poison every subtraction
    // it took part in with nothing anywhere naming the field.
    expect(() =>
      dto.interactionEventDto.parse({
        browser_session_id: SESSION,
        install_id: INSTALL,
        seq: 1,
        kind: 'ViewEntered',
        view: 'home',
        occurred_at: 'the day before yesterday',
      }),
    ).toThrow(/occurred_at/)
  })
})

describe('toBrowserSession', () => {
  it('keeps event_count and max_seq apart', () => {
    const session = toBrowserSession(
      parsed(dto.browserSessionRowDto, {
        browser_session_id: SESSION,
        install_id: INSTALL,
        started_at: '2026-08-25T14:00:00Z',
        ended_at: '2026-08-25T14:30:00Z',
        // The disagreement is the point: 140 arrived, the browser counted to
        // 143, so delivery lost three. No other surface can show that, and
        // folding the two into one number would erase it.
        event_count: 140,
        max_seq: 143,
        views: ['home', 'project/catalog'],
        project_ids: [PROJECT],
        kinds: { ViewEntered: 12 },
      }),
    )

    expect(session.eventCount).toBe(140)
    expect(session.maxSeq).toBe(143)
    expect(session.projectIds).toEqual([PROJECT])
    expect(session.kinds).toEqual([{ kind: 'ViewEntered', count: 12 }])
  })

  it('reads a session with no bounded instants as null at both ends', () => {
    const page = toBrowserSessionPage(
      parsed(dto.browserSessionPageDto, {
        sessions: [
          {
            browser_session_id: SESSION,
            install_id: INSTALL,
            started_at: null,
            ended_at: null,
            event_count: 0,
            max_seq: 0,
          },
        ],
        total: 1,
      }),
    )

    expect(page.total).toBe(1)
    expect(page.sessions[0]?.startedAt).toBeNull()
    expect(page.sessions[0]?.endedAt).toBeNull()
    expect(page.sessions[0]?.views).toEqual([])
  })
})

describe('toViewDwell', () => {
  it('reports a null median rather than a zero one', () => {
    // A view entered and never exited: there is nothing to take a median of.
    // Zero is a real dwell and would read as a page nobody stayed on, which is
    // the opposite of what happened.
    const dwell = toViewDwell(
      parsed(dto.viewDwellDto, {
        view: 'interactions',
        entries: 4,
        exits: 0,
        dwell_ms_median: null,
        dwell_ms_p90: null,
        hidden_ms_median: null,
      }),
    )

    expect(dwell.dwellMsMedian).toBeNull()
    expect(dwell.dwellMsP90).toBeNull()
    expect(dwell.hiddenMsMedian).toBeNull()
    expect(dwell.entries).toBe(4)
    expect(dwell.exits).toBe(0)
  })

  it('keeps hidden time beside dwell rather than subtracting it', () => {
    const dwell = toViewDwell(
      parsed(dto.viewDwellDto, {
        view: 'project/catalog',
        entries: 812,
        exits: 806,
        dwell_ms_median: 2310,
        dwell_ms_p90: 18400,
        hidden_ms_median: 400,
      }),
    )

    // 2310, not 1910. The consumer chooses whether to subtract; this layer
    // does not choose for them.
    expect(dwell.dwellMsMedian).toBe(2310)
    expect(dwell.hiddenMsMedian).toBe(400)
  })
})

describe('toApprovalSummary', () => {
  it('reads an empty window as null latencies and no decisions', () => {
    const approvals = toApprovalSummary(
      parsed(dto.approvalSummaryDto, {
        total: 0,
        expanded: 0,
        median_latency_ms: null,
        median_latency_ms_expanded: null,
        median_latency_ms_plain: null,
        by_decision: {},
      }),
    )

    expect(approvals.medianLatencyMs).toBeNull()
    expect(approvals.medianLatencyMsExpanded).toBeNull()
    expect(approvals.medianLatencyMsPlain).toBeNull()
    expect(approvals.byDecision).toEqual([])
  })

  it('keeps the expanded and plain latencies apart', () => {
    const approvals = toApprovalSummary(
      parsed(dto.approvalSummaryDto, {
        total: 40,
        expanded: 12,
        median_latency_ms: 3900,
        median_latency_ms_expanded: 14200,
        // Only 28 of the 40 were plain, so this is not a median over `total`
        // and must not be derived from the other two.
        median_latency_ms_plain: 900,
        by_decision: { approved: 33, rejected: 7 },
      }),
    )

    expect(approvals.medianLatencyMsExpanded).toBe(14200)
    expect(approvals.medianLatencyMsPlain).toBe(900)
    expect(approvals.byDecision).toEqual([
      { decision: 'approved', count: 33 },
      { decision: 'rejected', count: 7 },
    ])
  })

  it('carries a decision the console has never heard of', () => {
    // The vocabulary is the server's. Dropping an unrecognised decision would
    // hide exactly the event worth noticing, and would make the parts stop
    // summing to `total` with nothing saying why.
    const approvals = toApprovalSummary(
      parsed(dto.approvalSummaryDto, {
        total: 1,
        expanded: 0,
        median_latency_ms: null,
        median_latency_ms_expanded: null,
        median_latency_ms_plain: null,
        by_decision: { deferred: 1 },
      }),
    )

    expect(approvals.byDecision).toEqual([{ decision: 'deferred', count: 1 }])
  })
})

describe('toInteractionSummary', () => {
  it('folds the four blocks and keeps the friction places ordered', () => {
    const summary = toInteractionSummary(
      parsed(dto.interactionSummaryDto, {
        by_kind: { SearchPerformed: 61, EmptyResultEncountered: 96 },
        by_view: [
          {
            view: 'project/catalog',
            entries: 812,
            exits: 806,
            dwell_ms_median: 2310,
            dwell_ms_p90: 18400,
            hidden_ms_median: 0,
          },
        ],
        friction: {
          undone: 14,
          retried: 31,
          empty_results: 96,
          empty_by_where: [
            { where: 'search', count: 61 },
            { where: 'graph', count: 35 },
          ],
          repeat_searches: 22,
        },
        approvals: {
          total: 40,
          expanded: 12,
          median_latency_ms: 3900,
          median_latency_ms_expanded: 14200,
          median_latency_ms_plain: 900,
          by_decision: { approved: 33, rejected: 7 },
        },
      }),
    )

    expect(summary.byKind).toEqual([
      { kind: 'SearchPerformed', count: 61 },
      { kind: 'EmptyResultEncountered', count: 96 },
    ])
    expect(summary.byView[0]?.view).toBe('project/catalog')
    // 0 and not null: this view was exited with no time hidden, which is a
    // measurement, unlike the null above.
    expect(summary.byView[0]?.hiddenMsMedian).toBe(0)
    expect(summary.friction.emptyByWhere).toEqual([
      { where: 'search', count: 61 },
      { where: 'graph', count: 35 },
    ])
    expect(summary.friction.repeatSearches).toBe(22)
    expect(summary.approvals.expanded).toBe(12)
  })
})

/** The five fields the server sends and this console must never read.
 *
 * `InteractionEventRow` extends eventsource's `ReadModel`, so every row
 * carries `id`, `version`, `created_at`, `updated_at` and `deleted_at`
 * alongside the ten the explorer wants. Measured against a real response
 * shape on 2026-08-25, after T2 flagged it: zod strips an undeclared key
 * rather than failing on it, so nothing breaks -- which is exactly why this
 * needs a test. A silent strip and a silent bind look identical from here.
 *
 * `created_at` is the dangerous one. It is when the projection wrote the row,
 * not when the interaction happened, and it is a plausible-looking instant on
 * the same object as `occurred_at`. A feed bound to it would be wrong by the
 * projection's lag, consistently, with nothing on screen disagreeing.
 */
describe('read-model bookkeeping', () => {
  it('strips the five fields the explorer must not read', () => {
    const raw = {
      id: 'a3f9-derived-from-session-and-seq',
      version: 3,
      // A year and a half before `occurred_at` below, so a mapper that bound
      // the wrong field would be caught by the value and not only by the key.
      created_at: '2025-01-01T00:00:00Z',
      updated_at: '2025-01-01T00:00:00Z',
      deleted_at: null,
      browser_session_id: SESSION,
      install_id: INSTALL,
      seq: 1,
      kind: 'ViewEntered',
      view: 'home',
      occurred_at: '2026-08-25T14:00:00Z',
    }

    const parsed = dto.interactionEventDto.parse(raw)
    expect(Object.keys(parsed).sort()).toEqual([
      'browser_session_id',
      'install_id',
      'kind',
      'occurred_at',
      'payload',
      'project_id',
      'received_at',
      'seq',
      'session_id',
      'view',
    ])

    const event = toLoggedInteraction(parsed)
    expect(event.occurredAt.toISOString()).toBe('2026-08-25T14:00:00.000Z')
    // Named explicitly: the assertion is that nothing anywhere on the domain
    // object holds the row's write time.
    expect(JSON.stringify(event)).not.toContain('2025-01-01')
  })
})
