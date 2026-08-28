import { expect, it } from 'vitest'

import type { Project } from './project.ts'
import type { SessionSummary } from '../session/session.ts'
import { ProjectId, SessionId } from '../shared/identifier.ts'

import {
  currentSession,
  flatten,
  forest,
  matches,
  recencyOf,
  rollups,
  summariesAsForest,
} from './landing.ts'

const ATLAS = ProjectId('11111111-1111-1111-1111-111111111111')
const RETENTION = ProjectId('22222222-2222-2222-2222-222222222222')

const project = (id: ProjectId, name: string, over: Partial<Project> = {}): Project => ({
  id,
  name,
  activeSessionId: null,
  tipAtEvent: 0,
  ...over,
})

const session = (id: string, over: Partial<SessionSummary> = {}): SessionSummary => ({
  id: SessionId(id),
  projectId: ATLAS,
  startedAt: '2026-08-01T00:00:00Z',
  turns: 0,
  files: 0,
  firstMessage: null,
  forkedFrom: null,
  forkedAt: null,
  failedTurns: 0,
  ...over,
})

/** Moved here with the function, from `infrastructure/http/mappers.test.ts`.
 *
 * The second assertion is the one that is not a restatement of the first: it
 * pins that lineage is *dropped* rather than rebuilt, which is what separates
 * this from `forest` and is the only way the two could be silently swapped. It
 * would fail against `forest`, which would nest `b` under `a`. */
it('renders a flat list as roots, discarding lineage rather than guessing at it', () => {
  const roots = summariesAsForest([session('a'), session('b', { forkedFrom: SessionId('a') })])

  expect(roots.map((root) => root.id)).toEqual(['a', 'b'])
  expect(roots.every((root) => root.children.length === 0)).toBe(true)
})

it('puts each session under the project it belongs to', () => {
  const [first] = rollups(
    [project(ATLAS, 'atlas')],
    [session('a', { projectId: ATLAS }), session('b', { projectId: RETENTION })],
  )

  expect(first!.sessionCount).toBe(1)
  expect(flatten(first!.sessions).map((row) => row.id)).toEqual(['a'])
})

it('ranks projects by their most recent session, and puts empty ones last', () => {
  const ranked = rollups(
    [project(ATLAS, 'atlas'), project(RETENTION, 'retention-review')],
    [
      session('old', { projectId: ATLAS, startedAt: '2026-01-01T00:00:00Z' }),
      session('new', { projectId: RETENTION, startedAt: '2026-08-01T00:00:00Z' }),
    ],
  )

  expect(ranked.map((rollup) => rollup.project.name)).toEqual(['retention-review', 'atlas'])

  const withEmpty = rollups(
    [project(ATLAS, 'atlas'), project(RETENTION, 'brand-new')],
    [session('old', { projectId: ATLAS, startedAt: '2026-01-01T00:00:00Z' })],
  )
  expect(withEmpty.map((rollup) => rollup.project.name)).toEqual(['atlas', 'brand-new'])
})

it('keeps fork lineage inside a project, newest root first', () => {
  const [only] = rollups(
    [project(ATLAS, 'atlas')],
    [
      session('root', { projectId: ATLAS, startedAt: '2026-01-01T00:00:00Z' }),
      session('fork', {
        projectId: ATLAS,
        startedAt: '2026-02-01T00:00:00Z',
        forkedFrom: SessionId('root'),
        forkedAt: 31,
      }),
      session('later-root', { projectId: ATLAS, startedAt: '2026-03-01T00:00:00Z' }),
    ],
  )

  expect(only!.sessions.map((node) => node.id)).toEqual(['later-root', 'root'])
  expect(only!.sessions[1]!.children.map((node) => node.id)).toEqual(['fork'])
})

it('makes a fork whose parent is in another project a root of its own', () => {
  // Nesting across a project boundary would draw a session inside a project it
  // is not in, which is the one thing grouping must not do.
  const [atlas] = rollups(
    [project(ATLAS, 'atlas')],
    [
      session('parent', { projectId: RETENTION }),
      session('child', { projectId: ATLAS, forkedFrom: SessionId('parent') }),
    ],
  )

  expect(atlas!.sessions.map((node) => node.id)).toEqual(['child'])
  expect(atlas!.sessions[0]!.children).toEqual([])
})

it('does not lose a session whose fork parent it has never heard of', () => {
  // The server's `build_fork_tree` has the same rule, and for the same reason:
  // an absent ancestor must cost a level of indentation, not a row.
  const roots = forest([session('orphan', { forkedFrom: SessionId('gone') })])

  expect(roots.map((node) => node.id)).toEqual(['orphan'])
})

it('searches project names and the one field a human wrote', () => {
  const [atlas] = rollups(
    [project(ATLAS, 'atlas')],
    [session('a', { projectId: ATLAS, firstMessage: 'How does spacing affect retention?' })],
  )

  expect(matches(atlas!, 'atl')).toBe(true)
  expect(matches(atlas!, 'SPACING')).toBe(true)
  expect(matches(atlas!, 'fizzbuzz')).toBe(false)
  expect(matches(atlas!, '   ')).toBe(true)
})

it('buckets a project by the same timestamp its row prints', () => {
  const now = Date.parse('2026-08-09T12:00:00Z')
  const at = (startedAt: string) =>
    rollups([project(ATLAS, 'atlas')], [session('a', { projectId: ATLAS, startedAt })])[0]!

  expect(recencyOf(at('2026-08-09T09:00:00Z'), now)).toBe('today')
  expect(recencyOf(at('2026-08-06T09:00:00Z'), now)).toBe('week')
  expect(recencyOf(at('2026-01-06T09:00:00Z'), now)).toBe('older')
  expect(recencyOf(rollups([project(ATLAS, 'atlas')], [])[0]!, now)).toBe('empty')
})

it('picks the holding session as a project’s current one, not merely the newest', () => {
  // "Where was I" is the holder: it is the session still open, and the one
  // `Resume` goes to. A newer fork made from it is not where you were.
  const [atlas] = rollups(
    [project(ATLAS, 'atlas', { activeSessionId: SessionId('holder') })],
    [
      session('holder', { projectId: ATLAS, startedAt: '2026-01-01T00:00:00Z' }),
      session('newer', { projectId: ATLAS, startedAt: '2026-08-01T00:00:00Z' }),
    ],
  )

  expect(currentSession(atlas!)?.id).toBe('holder')
})

it('falls back to the newest session when nothing holds the project', () => {
  const [atlas] = rollups(
    [project(ATLAS, 'atlas')],
    [
      session('older', { projectId: ATLAS, startedAt: '2026-01-01T00:00:00Z' }),
      session('newest', { projectId: ATLAS, startedAt: '2026-08-01T00:00:00Z' }),
    ],
  )

  expect(currentSession(atlas!)?.id).toBe('newest')
})

it('falls back to the newest when the holder is missing from the session list', () => {
  // A row showing no session at all would read as a project nothing has run
  // in, which is a different and false statement.
  const [atlas] = rollups(
    [project(ATLAS, 'atlas', { activeSessionId: SessionId('not-listed') })],
    [session('present', { projectId: ATLAS })],
  )

  expect(currentSession(atlas!)?.id).toBe('present')
})

it('has no current session for a project nothing has run in', () => {
  const [atlas] = rollups([project(ATLAS, 'atlas')], [])

  expect(currentSession(atlas!)).toBeNull()
})
