import { describe, expect, it } from 'vitest'

import * as dto from './dto.ts'
import {
  summariesAsForest,
  toCourse,
  toForkNode,
  toLogEntry,
  toMessage,
  toRoster,
  toRun,
  toSession,
  toTurnRange,
} from './mappers.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

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

describe('toForkNode', () => {
  it('maps a tree to any depth', () => {
    const node = toForkNode(
      parse(dto.forkNodeDto, {
        id: 'a',
        children: [{ id: 'b', children: [{ id: 'c', children: [] }] }],
      }),
    )
    expect(node.children[0]?.children[0]?.id).toBe('c')
  })
})

describe('summariesAsForest', () => {
  it('renders a flat list as roots, for when the tree projection has drifted', () => {
    // A truthful degradation; "no sessions yet" would be a lie.
    const forest = summariesAsForest([
      {
        id: 'a',
        startedAt: null,
        turns: null,
        files: null,
        firstMessage: null,
        forkedFrom: null,
        forkedAt: null,
        failedTurns: null,
      },
    ] as never)
    expect(forest[0]?.children).toEqual([])
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

describe('toCourse', () => {
  it('carries the project id the source links are addressed by', () => {
    const course = toCourse(
      parse(dto.courseDto, { preset: { id: 'hybrid', name: 'Hybrid' } }),
      ProjectId('p1'),
    )
    expect(course.projectId).toBe('p1')
  })

  it('renames live_findings to what the view actually calls them', () => {
    const course = toCourse(
      parse(dto.courseDto, {
        preset: { id: 'h', name: 'H' },
        live_findings: [{ check: 'c', severity: 'blocking', message: 'm' }],
        unimplemented_checks: ['x'],
      }),
      ProjectId('p1'),
    )
    expect(course.findings[0]?.check).toBe('c')
    expect(course.unimplementedChecks).toEqual(['x'])
  })

  it('keeps an unresolvable position null rather than inventing one', () => {
    const course = toCourse(
      parse(dto.courseDto, { preset: { id: 'h', name: 'H' } }),
      ProjectId('p1'),
    )
    expect(course.position).toBeNull()
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
})
