import { describe, expect, it } from 'vitest'

import { ProjectId } from '../shared/identifier.ts'

import { board, extractedFraction, isBehind, progressOf, scaleOf } from './board.ts'
import type { ProjectListing, ProjectSummary } from './project.ts'

const EMPTY: ProjectSummary = {
  topics: 0,
  topicsOpen: 0,
  sources: 0,
  extracted: 0,
  courses: 0,
  sessions: 0,
  lastActivity: null,
}

let next = 0
const listing = (name: string, summary: Partial<ProjectSummary> = {}): ProjectListing => ({
  id: ProjectId(`0000000${(next += 1)}-1111-4111-8111-111111111111`),
  name,
  activeSessionId: null,
  tipAtEvent: 0,
  summary: { ...EMPTY, ...summary },
})

describe('scaleOf', () => {
  it('takes the largest value of each stage independently', () => {
    // The three maxima come from three *different* projects, which is the case
    // a fixture with one dominant project could not distinguish: a scale that
    // took "the biggest project" rather than "the biggest of each stage" would
    // agree with this on any input where one project led everywhere.
    const scale = scaleOf([
      listing('a', { topics: 20, sources: 1, courses: 1 }),
      listing('b', { topics: 1, sources: 30, courses: 1 }),
      listing('c', { topics: 1, sources: 1, courses: 4 }),
    ])

    expect(scale).toEqual({ topics: 20, sources: 30, courses: 4 })
  })

  it('floors every stage at one so an all-empty board divides by one', () => {
    // Not cosmetic: a zero here reaches the view as `0 / 0`, and `NaN%` is not
    // a length, so the bar keeps whatever width it last had rather than
    // drawing empty.
    expect(scaleOf([listing('a'), listing('b')])).toEqual({
      topics: 1,
      sources: 1,
      courses: 1,
    })
  })

  it('floors an empty board rather than returning -Infinity', () => {
    // `Math.max()` with no arguments is `-Infinity`. Reached whenever the
    // query has answered with an empty array, which is a real state.
    expect(scaleOf([])).toEqual({ topics: 1, sources: 1, courses: 1 })
  })
})

describe('extraction', () => {
  it('reports a project with no sources as complete, not as behind', () => {
    // The case worth arguing: "nothing ingested" is not "extraction is
    // behind". Returning 0 here would paint a full amber bar on every project
    // nobody has started, turning the marker for work outstanding into the
    // marker for an empty project — the exact inversion of what it is for.
    expect(extractedFraction(EMPTY)).toBe(1)
    expect(isBehind(EMPTY)).toBe(false)
  })

  it('is behind exactly when some ingested source has not been extracted', () => {
    expect(isBehind({ ...EMPTY, sources: 6, extracted: 3 })).toBe(true)
    expect(extractedFraction({ ...EMPTY, sources: 6, extracted: 3 })).toBe(0.5)
    expect(isBehind({ ...EMPTY, sources: 6, extracted: 6 })).toBe(false)
  })
})

describe('progressOf', () => {
  /** Parametrised over the property that *distinguishes* the formula chosen
   *  from the one rejected, rather than over a representative example.
   *
   * The rejected formula counted the extraction stage as reached when
   * `extracted > 0`. It agrees with the chosen one on every project that has
   * extracted all of its sources or none of them — which is five of the six on
   * the real database, and every case anyone would think to write down. They
   * differ only on a *partially* extracted project, which is the third row
   * below. CLAUDE.md's rule: if you cannot say which input separates your
   * formula from the one you rejected, you have not tested the choice.
   */
  it.each([
    ['nothing at all', EMPTY, 0],
    ['topics only', { ...EMPTY, topics: 4 }, 0.25],
    [
      'ingest begun but extraction incomplete',
      { ...EMPTY, topics: 4, sources: 6, extracted: 3 },
      0.5,
    ],
    ['ingest fully extracted', { ...EMPTY, topics: 4, sources: 6, extracted: 6 }, 0.75],
    ['every stage reached', { ...EMPTY, topics: 4, sources: 6, extracted: 6, courses: 2 }, 1],
  ])('scores %s at %#', (_name, summary, expected) => {
    expect(progressOf(summary)).toBe(expected)
  })

  it('does not credit the extraction stage to a project with no sources', () => {
    // `extracted === sources` is trivially true at 0 and 0, so a formula
    // written as that comparison alone would score an empty project as having
    // finished extracting. The `sources > 0` conjunct is what this covers, and
    // it is the clause most likely to be dropped as redundant.
    expect(progressOf(EMPTY)).toBe(0)
  })
})

describe('board', () => {
  const projects = [
    listing('atlas', { sources: 1, lastActivity: '2026-08-01T00:00:00Z' }),
    listing('spacing', {
      topics: 4,
      sources: 6,
      extracted: 6,
      courses: 1,
      lastActivity: '2026-08-03T00:00:00Z',
    }),
    listing('retention', { topics: 2, lastActivity: '2026-08-02T00:00:00Z' }),
  ]

  it('orders by real recency, newest first', () => {
    expect(board(projects, '', 'recent').map((one) => one.name)).toEqual([
      'spacing',
      'retention',
      'atlas',
    ])
  })

  it('sorts a project nobody has opened to the bottom rather than the top', () => {
    // A null timestamp compares as the empty string. Sorted the other way it
    // would lead the board, so the first thing a returning reader sees would
    // be the project with nothing in it.
    const withEmpty = [...projects, listing('brand new')]

    expect(board(withEmpty, '', 'recent').at(-1)?.name).toBe('brand new')
  })

  it('orders by pipeline progress, breaking ties on recency', () => {
    // `atlas` and `retention` are both at one stage of four, so the tie-break
    // is the whole content of their relative order — and without it the two
    // would sit in whatever order the server returned, reshuffling on every
    // refetch.
    expect(board(projects, '', 'progress').map((one) => one.name)).toEqual([
      'spacing',
      'retention',
      'atlas',
    ])
  })

  it('orders by name', () => {
    expect(board(projects, '', 'name').map((one) => one.name)).toEqual([
      'atlas',
      'retention',
      'spacing',
    ])
  })

  it('filters before it sorts, so an ordering is over what is on screen', () => {
    expect(board(projects, 'ten', 'name').map((one) => one.name)).toEqual(['retention'])
  })

  it('matches a project name case-insensitively and ignores surrounding space', () => {
    expect(board(projects, '  ATL ', 'name').map((one) => one.name)).toEqual(['atlas'])
  })

  it('returns everything for a blank search', () => {
    expect(board(projects, '   ', 'name')).toHaveLength(3)
  })

  it('does not reorder the array it was given', () => {
    // `sort` mutates, and the input here is a React Query cache entry in
    // production. Sorting it in place re-renders nothing, so the list would
    // silently keep whatever order the last sort left.
    const before = projects.map((one) => one.name)
    board(projects, '', 'name')

    expect(projects.map((one) => one.name)).toEqual(before)
  })
})
