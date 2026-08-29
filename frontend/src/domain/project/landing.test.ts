import { expect, it } from 'vitest'

import type { SessionSummary } from '../session/session.ts'
import { SessionId } from '../shared/identifier.ts'

import { flatten, forest, summariesAsForest } from './landing.ts'

/** Fork lineage, and nothing else.
 *
 * **Most of this file went with the functions it covered.** `rollups`,
 * `currentSession`, `recencyOf` and `matches` are deleted -- the index does not
 * arrange projects around their sessions any more -- and their tests are
 * deleted with them rather than rewritten against `board.ts`, which answers
 * different questions from different data. `board.test.ts` is that file.
 *
 * What is kept is what was never about the index: rebuilding a fork forest,
 * where a parent may belong to another project or to none.
 */

const session = (id: string, over: Partial<SessionSummary> = {}): SessionSummary => ({
  id: SessionId(id),
  projectId: '11111111-1111-1111-1111-111111111111' as SessionSummary['projectId'],
  startedAt: '2026-08-01T00:00:00Z',
  turns: 0,
  files: 0,
  firstMessage: null,
  forkedFrom: null,
  forkedAt: null,
  failedTurns: 0,
  ...over,
})

/** The second assertion is the one that is not a restatement of the first: it
 *  pins that lineage is *dropped* rather than rebuilt, which is what separates
 *  this from `forest` and is the only way the two could be silently swapped. It
 *  would fail against `forest`, which would nest `b` under `a`. */
it('renders a flat list as roots, discarding lineage rather than guessing at it', () => {
  const roots = summariesAsForest([session('a'), session('b', { forkedFrom: SessionId('a') })])

  expect(roots.map((root) => root.id)).toEqual(['a', 'b'])
  expect(roots.every((root) => root.children.length === 0)).toBe(true)
})

it('nests a fork under its parent, newest root first and children in order', () => {
  const roots = forest([
    session('root', { startedAt: '2026-01-01T00:00:00Z' }),
    session('fork', { startedAt: '2026-02-01T00:00:00Z', forkedFrom: SessionId('root') }),
    session('later-root', { startedAt: '2026-03-01T00:00:00Z' }),
  ])

  expect(roots.map((node) => node.id)).toEqual(['later-root', 'root'])
  expect(roots[1]!.children.map((node) => node.id)).toEqual(['fork'])
})

it('does not lose a session whose fork parent it has never heard of', () => {
  // The server's `build_fork_tree` has the same rule, and for the same reason:
  // an absent ancestor must cost a level of indentation, not a row.
  const roots = forest([session('orphan', { forkedFrom: SessionId('gone') })])

  expect(roots.map((node) => node.id)).toEqual(['orphan'])
})

it('flattens a forest depth-first, parent before child', () => {
  const roots = forest([
    session('root'),
    session('fork', { startedAt: '2026-02-01T00:00:00Z', forkedFrom: SessionId('root') }),
  ])

  expect(flatten(roots).map((node) => node.id)).toEqual(['root', 'fork'])
})
