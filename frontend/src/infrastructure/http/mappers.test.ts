import { describe, expect, it } from 'vitest'

import * as dto from './dto.ts'
import {
  toApproval,
  toForkNode,
  toGraphLink,
  toGraphNode,
  toLogEntry,
  toMessage,
  toNeighborhood,
  toProjectDetail,
  toRoster,
  toRun,
  toSession,
  toSessionSummary,
  toTurnRange,
  toWholeGraph,
} from './mappers.ts'

/** The boundary. A mapper bug does not throw — it renders a blank row or the
 *  wrong number — so these go through the real schemas rather than hand-built
 *  objects, which is what makes them a check of the *contract* and not of the
 *  mapper's own opinion of it. */
const parse = <S extends { parse: (v: unknown) => unknown }>(schema: S, raw: unknown) =>
  schema.parse(raw) as never

describe('toLogEntry', () => {
  it('renames every field the server spells differently', () => {
    const entry = toLogEntry(
      parse(dto.logEntryDto, {
        index: 4,
        type: 'FileEdited',
        occurred_at: '2026-01-01T00:00:00Z',
        summary: 'edited',
        path: '/a.md',
        turn_index: 2,
        is_error: false,
        cancelled: null,
      }),
    )
    expect(entry).toEqual({
      index: 4,
      type: 'FileEdited',
      occurredAt: '2026-01-01T00:00:00Z',
      summary: 'edited',
      path: '/a.md',
      turnIndex: 2,
      isError: false,
      cancelled: null,
    })
  })

  it('accepts a row with every optional field absent', () => {
    const entry = toLogEntry(
      parse(dto.logEntryDto, { index: 1, type: 'X', occurred_at: '2026-01-01T00:00:00Z' }),
    )
    expect(entry.summary).toBe('')
    expect(entry.path).toBeNull()
    expect(entry.cancelled).toBeNull()
  })
})

describe('toMessage', () => {
  it('maps the three roles', () => {
    for (const role of ['user', 'assistant', 'tool']) {
      expect(toMessage(parse(dto.messageDto, { role })).role).toBe(role)
    }
  })

  it('renders an unfamiliar role as an assistant turn rather than dropping it', () => {
    expect(toMessage(parse(dto.messageDto, { role: 'system' })).role).toBe('assistant')
  })

  it('reads an error status', () => {
    expect(toMessage(parse(dto.messageDto, { role: 'tool', is_error: true })).isError).toBe(true)
  })

  it('defaults tool calls to none', () => {
    expect(toMessage(parse(dto.messageDto, { role: 'user' })).toolCalls).toEqual([])
  })
})

describe('toSession', () => {
  it('carries the process facts the scrub bar reads', () => {
    const session = toSession(
      parse(dto.sessionDto, {
        id: 's1',
        project_id: 'p1',
        holds_project: false,
        knowledge_attached: true,
        files: [{ path: '/a.md', size: 12, revisions: 2 }],
      }),
    )
    expect(session.projectId).toBe('p1')
    expect(session.holdsProject).toBe(false)
    expect(session.knowledgeAttached).toBe(true)
    expect(session.files[0]?.path.basename).toBe('a.md')
  })

  it('keeps "the caller did not ask" distinct from "no"', () => {
    const session = toSession(parse(dto.sessionDto, { id: 's1' }))
    expect(session.holdsProject).toBeNull()
    expect(session.knowledgeAttached).toBeNull()
    expect(session.projectId).toBeNull()
  })
})

describe('toSessionSummary', () => {
  it('reads the project every session row belongs to', () => {
    expect(
      toSessionSummary(parse(dto.sessionSummaryDto, { id: 's1', project_id: 'p1' })).projectId,
    ).toBe('p1')
  })

  it('refuses a row with no project rather than carrying a null inwards', () => {
    // The shape a pre-#65 backend served. Asserting the schema rejects it is
    // what makes `SessionSummary.projectId` non-nullable a fact rather than a
    // hope: everything downstream stopped checking, so this is the only place
    // left that would notice.
    expect(() => dto.sessionSummaryDto.parse({ id: 's1', project_id: null })).toThrow()
    expect(() => dto.sessionSummaryDto.parse({ id: 's1' })).toThrow()
  })
})

describe('toForkNode', () => {
  it('maps a tree to any depth', () => {
    const node = toForkNode(
      parse(dto.forkNodeDto, {
        id: 'a',
        project_id: 'p1',
        children: [
          { id: 'b', project_id: 'p1', children: [{ id: 'c', project_id: 'p1', children: [] }] },
        ],
      }),
    )
    expect(node.children[0]?.children[0]?.id).toBe('c')
  })
})

describe('toTurnRange', () => {
  it('reads a span the turn reported', () => {
    expect(
      toTurnRange(parse(dto.turnResultDto, { turn_index: 3, from_index: 4, to_index: 9 })),
    ).toEqual({ turnIndex: 3, from: 4, to: 9 })
  })

  it('is null unless both ends are present — a range with one end is not a range', () => {
    expect(toTurnRange(parse(dto.turnResultDto, { from_index: 4 }))).toBeNull()
    expect(toTurnRange(parse(dto.turnResultDto, {}))).toBeNull()
  })
})

describe('toRun', () => {
  const ids = { run_id: 'r', project_id: 'p', session_id: 's' }

  it('reads the 202 body as a run with no fold yet, not as zeroed counters', () => {
    // "0 rounds" and "not folded" are different facts.
    expect(toRun(parse(dto.runDto, ids)).progress).toBeNull()
  })

  it('reads a folded run', () => {
    const run = toRun(
      parse(dto.runDto, {
        ...ids,
        status: 'stopped',
        rounds: 4,
        turns: 4,
        findings: 2,
        stop_reason: 'queue_empty',
        quiet_rounds: 1,
        failures: 0,
        budget: { max_rounds: 10, quiet_rounds: 3 },
        read_only: true,
      }),
    )
    expect(run.progress).toMatchObject({
      status: 'stopped',
      rounds: 4,
      findings: 2,
      stopReason: 'queue_empty',
      quietRounds: 1,
      readOnly: true,
      budget: { maxRounds: 10, quietRounds: 3 },
    })
  })

  it('reads an uncapped budget as uncapped rather than as zero', () => {
    const run = toRun(parse(dto.runDto, { ...ids, status: 'running' }))
    expect(run.progress?.budget.maxRounds).toBeNull()
  })
})

describe('toRoster', () => {
  it('maps the wire shape, parsing timestamps to epoch milliseconds', () => {
    const roster = toRoster(
      parse(dto.rosterDto, {
        project_id: '11111111-1111-1111-1111-111111111111',
        workers: [
          {
            kind: 'run',
            ref: 'run-1',
            detail: 'autonomous run',
            session_id: '22222222-2222-2222-2222-222222222222',
            parent: null,
            started_at: '2026-08-07T12:00:00+00:00',
          },
        ],
        idle_session_ids: ['33333333-3333-3333-3333-333333333333'],
      }),
    )

    expect(roster.workers[0]?.kind).toBe('run')
    expect(roster.workers[0]?.sessionId).toBe('22222222-2222-2222-2222-222222222222')
    expect(roster.workers[0]?.startedAt).toBe(Date.parse('2026-08-07T12:00:00+00:00'))
    expect(roster.idleSessionIds).toEqual(['33333333-3333-3333-3333-333333333333'])
  })

  it('keeps a null start time null rather than turning it into now', () => {
    // A worker with no start time must not render as "0s elapsed", which
    // reads as having just begun.
    const roster = toRoster(
      parse(dto.rosterDto, {
        project_id: '11111111-1111-1111-1111-111111111111',
        workers: [
          {
            kind: 'extraction',
            ref: 'src-1',
            detail: 'extracting',
            session_id: null,
            parent: 'run-1',
            started_at: null,
          },
        ],
        idle_session_ids: [],
      }),
    )

    expect(roster.workers[0]?.startedAt).toBeNull()
    expect(roster.workers[0]?.sessionId).toBeNull()
  })

  it('keeps a stage runner labelled as a stage rather than folding it into turn', () => {
    // The trap #79 fixed for dispatch, guarded for the kind added after it:
    // the fallback is `turn`, which is a different specific kind, so an
    // unmapped `stage` would render as a confident wrong answer. Fails if the
    // server grows a kind the mapper is not told about.
    const roster = toRoster(
      parse(dto.rosterDto, {
        project_id: '11111111-1111-1111-1111-111111111111',
        workers: [
          {
            kind: 'stage',
            ref: 'ubd.stage2.evidence',
            detail: 'ubd.pure · ubd.stage2.evidence · turn 2',
            session_id: '22222222-2222-2222-2222-222222222222',
            parent: null,
            started_at: null,
          },
        ],
        idle_session_ids: [],
      }),
    )

    expect(roster.workers[0]?.kind).toBe('stage')
  })
})

describe('toNeighborhood', () => {
  it('renames the wire fields on the root, its entities and its relationships', () => {
    const neighborhood = toNeighborhood(
      parse(dto.graphNeighborhoodDto, {
        root: { entity_id: 'ada', name: 'Ada Lovelace', entity_type: 'Person' },
        entities: [
          { entity_id: 'ada', name: 'Ada Lovelace', entity_type: 'Person' },
          { entity_id: 'grace', name: 'Grace Hopper', entity_type: 'Person' },
        ],
        relationships: [{ source_id: 'ada', target_id: 'grace', relationship_type: 'advised' }],
      }),
    )

    expect(neighborhood.root).toEqual({
      id: 'ada',
      name: 'Ada Lovelace',
      entityType: 'Person',
      // Present and false on every node, not only synthesised ones, so a
      // client never has to read an absent key as "not inferred".
      inferred: false,
      temporal: null,
    })
    expect(neighborhood.entities).toHaveLength(2)
    expect(neighborhood.relationships).toEqual([
      {
        source: 'ada',
        target: 'grace',
        relationshipType: 'advised',
        inferred: false,
        derivation: null,
      },
    ])
  })
})

describe('toGraphNode', () => {
  it('carries the entity temporal extent through', () => {
    const node = toGraphNode(
      parse(dto.graphEntityDto, {
        entity_id: 'ada',
        name: 'Ada Lovelace',
        entity_type: 'Person',
        temporal: '1815-1852',
      }),
    )

    expect(node.temporal).toBe('1815-1852')
  })
})

describe('toGraphLink', () => {
  it('carries inferred and derivation through', () => {
    const link = toGraphLink(
      parse(dto.graphRelationshipDto, {
        source_id: 'ada',
        target_id: 'grace',
        relationship_type: 'CONTAINS',
        inferred: true,
        derivation: 'ada contains grace by date range',
      }),
    )

    expect(link.inferred).toBe(true)
    expect(link.derivation).toBe('ada contains grace by date range')
  })
})

describe('toWholeGraph', () => {
  it('carries inferredTruncated through', () => {
    const graph = toWholeGraph(
      parse(dto.graphWholeDto, {
        entities: [],
        relationships: [],
        truncated: false,
        inferred_truncated: true,
      }),
    )

    expect(graph.inferredTruncated).toBe(true)
  })
})

describe('toApproval', () => {
  const legacy = { id: 'a1', session_id: 's1', tool_name: 'fetch' }

  it('offers nothing when the server names no decisions', () => {
    // A payload from before `allowed_decisions` existed. Defaulting to every
    // decision instead would be the dangerous direction: a tool gate would
    // sprout a `respond` button the server rejects.
    expect(toApproval(parse(dto.approvalDto, legacy)).allowedDecisions).toEqual([])
  })

  it('drops a decision this build cannot post', () => {
    const approval = toApproval(
      parse(dto.approvalDto, {
        ...legacy,
        allowed_decisions: ['approve', 'defenestrate', 'respond'],
      }),
    )
    expect(approval.allowedDecisions).toEqual(['approve', 'respond'])
  })
})

it('carries a class node across as inferred', () => {
  // The flag decides whether the panel fetches a neighbourhood, so a mapper
  // that dropped it would leave every class node issuing a 404 on click --
  // and the drawing would look right the whole time.
  const node = toGraphNode(
    dto.graphEntityDto.parse({
      entity_id: 'difficulty',
      name: 'Difficulty',
      entity_type: 'class',
      inferred: true,
    }),
  )

  expect(node.inferred).toBe(true)
})

it('reads an entity written before the field existed as not inferred', () => {
  const node = toGraphNode(
    dto.graphEntityDto.parse({ entity_id: 'ada', name: 'Ada', entity_type: 'Person' }),
  )

  expect(node.inferred).toBe(false)
})

describe('toProjectDetail', () => {
  it('renames every field the server spells differently', () => {
    const project = toProjectDetail(
      parse(dto.projectDetailDto, {
        id: '11111111-1111-4111-8111-111111111111',
        name: 'atlas',
        active_session_id: '22222222-2222-4222-8222-222222222222',
        tip_at_event: 7,
      }),
    )

    expect(project).toEqual({
      id: '11111111-1111-4111-8111-111111111111',
      name: 'atlas',
      activeSessionId: '22222222-2222-4222-8222-222222222222',
      tipAtEvent: 7,
    })
  })

  it('reads an unheld project as a null holder rather than an empty string', () => {
    // The distinction the page turns on: `null` is "nobody has joined", which
    // is what hides the transcript and the composer. An empty string would be
    // truthy through `activeSessionId ?? null` and resolve to a session id of
    // `''`, which reads as held and 404s on the first request made with it.
    const project = toProjectDetail(
      parse(dto.projectDetailDto, {
        id: '11111111-1111-4111-8111-111111111111',
        name: 'atlas',
        active_session_id: null,
      }),
    )

    expect(project.activeSessionId).toBeNull()
    // Defaulted by the schema, not sent: an older server omits it entirely and
    // a project with no tip is 0, not `undefined` rendered as a blank.
    expect(project.tipAtEvent).toBe(0)
  })
})
