import { describe, expect, it } from 'vitest'

import { emptyTimeline, laneRows, spanOf, type TimelineBand } from './timeline.ts'

const band = (over: Partial<TimelineBand> & { id: string }): TimelineBand => ({
  name: over.id,
  entityType: 'event',
  extent: '',
  start: null,
  end: null,
  precision: 'YEAR',
  uncertainty: 'EXACT',
  ...over,
})

const year = (id: string, from: number, to: number, entityType = 'event'): TimelineBand =>
  band({
    id,
    entityType,
    start: `${from}-01-01T00:00:00`,
    end: `${to}-01-01T00:00:00`,
    extent: `${from}`,
  })

describe('laneRows', () => {
  it('gives each entity type its own lane, in first-appearance order', () => {
    const lanes = laneRows([year('a', 1800, 1801, 'person'), year('b', 1900, 1901, 'event')])

    expect(lanes.map((lane) => lane.entityType)).toEqual(['person', 'event'])
  })

  it('puts two bands that overlap in time on different rows', () => {
    // The correctness property the whole function exists for: two bars on one
    // row would draw on top of each other, and the one underneath is not
    // merely hard to read, it is invisible.
    const lanes = laneRows([year('a', 1800, 1850), year('b', 1820, 1870)])

    const [lane] = lanes
    expect(lane!.rows).toBe(2)
    expect(lane!.bands.map((positioned) => positioned.row)).toEqual([0, 1])
  })

  it('reuses a row once the previous band on it has ended', () => {
    // Packing rather than one row per band. A hundred sequential events each
    // on its own row is a diagonal line, not a timeline.
    const lanes = laneRows([year('a', 1800, 1810), year('b', 1820, 1830)])

    const [lane] = lanes
    expect(lane!.rows).toBe(1)
    expect(lane!.bands.map((positioned) => positioned.row)).toEqual([0, 0])
  })

  it('treats bands that merely touch as non-overlapping', () => {
    // A half-open interval: 1810 ends where 1810-1820 begins, and they share
    // no instant. Widening this to "touching counts as overlapping" would put
    // every consecutive year-precision pair on its own row -- which is the
    // diagonal-line failure above, reached by a different route.
    const lanes = laneRows([year('a', 1800, 1810), year('b', 1810, 1820)])

    expect(lanes[0]!.rows).toBe(1)
  })

  it('rows a band open at both ends against everything in its lane', () => {
    // An open bound is unbounded, not missing: a band running off both edges
    // overlaps every other band there is, so it cannot share a row with any.
    const lanes = laneRows([band({ id: 'open' }), year('a', 1800, 1810)])

    expect(lanes[0]!.rows).toBe(2)
  })

  it('has no lanes for no bands', () => {
    expect(laneRows([])).toEqual([])
  })
})

describe('spanOf', () => {
  it('spans from the earliest start to the latest end', () => {
    const span = spanOf([year('a', 1800, 1810), year('b', 1900, 1910)])

    expect(span).toEqual({
      from: Date.parse('1800-01-01T00:00:00'),
      to: Date.parse('1910-01-01T00:00:00'),
    })
  })

  it('ignores open bounds when computing the span', () => {
    // An axis cannot start at negative infinity. A band open below is drawn
    // running off the edge of whatever span the *bounded* bands establish,
    // which is why the open bound contributes nothing to it.
    const span = spanOf([band({ id: 'open' }), year('a', 1800, 1810)])

    expect(span).toEqual({
      from: Date.parse('1800-01-01T00:00:00'),
      to: Date.parse('1810-01-01T00:00:00'),
    })
  })

  it('reads the offset-suffixed instants the server actually sends', () => {
    // Every other fixture in this file writes a bare local-time string, which
    // is *not* the shape the wire carries: the backend calls `isoformat()` on
    // tz-aware datetimes, so a real `start` is `'1815-01-01T00:00:00+00:00'`.
    // Nothing tested that until this, and the two spellings parse to different
    // numbers on any machine not at UTC -- so a comparison mixing them (an
    // axis extreme hard-coded in the bare shape, say) would be wrong by the
    // offset and invisible in CI.
    const span = spanOf([
      band({
        id: 'utc',
        start: '1815-01-01T00:00:00+00:00',
        end: '1816-01-01T00:00:00+00:00',
      }),
    ])

    expect(span).toEqual({
      from: Date.UTC(1815, 0, 1),
      to: Date.UTC(1816, 0, 1),
    })
  })

  it('is null when nothing has a bounded date', () => {
    expect(spanOf([band({ id: 'open' })])).toBeNull()
    expect(spanOf([])).toBeNull()
  })
})

describe('emptyTimeline', () => {
  it('is empty rather than absent, so a pane can render before its first fetch', () => {
    expect(emptyTimeline.bands).toEqual([])
    expect(emptyTimeline.undatedCount).toBe(0)
    expect(emptyTimeline.truncated).toBe(false)
  })
})
