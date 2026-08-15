/** A project's dated entities, and how they pack onto rows.
 *
 * A pure fold: no fetching, no React, no store. Here rather than inside the
 * canvas because row packing has a correctness property that is easy to break
 * under refactoring pressure and impossible to see in a screenshot -- two
 * bands overlapping in time must never share a row, because the one drawn
 * second covers the first entirely.
 */

export interface TimelineBand {
  readonly id: string
  readonly name: string
  readonly entityType: string
  /** What the document said, already formatted: "1815", "November 1923".
   *  Distinct from `start`/`end`, which are the widened interval that gets
   *  drawn -- see the port's `TimelineBand.extent`. */
  readonly extent: string
  /** ISO instant, or `null` for open below -- an `UncertaintyMarker.BEFORE`,
   *  which is a claim about unboundedness rather than a missing value. */
  readonly start: string | null
  readonly end: string | null
  readonly precision: string
  readonly uncertainty: string
}

export interface Timeline {
  readonly bands: readonly TimelineBand[]
  /** Entities in this project with no drawable extent. Rendered, not dropped:
   *  a timeline is a view of a minority of any real corpus, and one with no
   *  denominator reads as the whole of it. */
  readonly undatedCount: number
  readonly truncated: boolean
}

export const emptyTimeline: Timeline = { bands: [], undatedCount: 0, truncated: false }

export interface PositionedBand {
  readonly band: TimelineBand
  readonly row: number
}

export interface Lane {
  readonly entityType: string
  readonly rows: number
  readonly bands: readonly PositionedBand[]
}

/** `-Infinity`/`Infinity` for an open bound, so comparisons need no special
 *  case. An open bound is unbounded, and that is exactly what these mean --
 *  the alternative, substituting the axis extremes, would make a band's
 *  overlap depend on what else happened to be on the timeline. */
const startOf = (band: TimelineBand): number =>
  band.start === null ? -Infinity : Date.parse(band.start)

const endOf = (band: TimelineBand): number => (band.end === null ? Infinity : Date.parse(band.end))

/** `bands` grouped by entity type, each group packed onto as few rows as it can
 *  take without two bands overlapping on one.
 *
 * Lanes are in first-appearance order rather than alphabetical: the bands
 * arrive sorted by time, so first-appearance means the lane whose earliest
 * event is earliest comes first, and the reader's eye travels down the page in
 * the same direction it travels across it.
 *
 * Greedy first-fit, which is not optimal and does not need to be: the optimal
 * packing is interval-graph colouring, the greedy pass over time-sorted
 * intervals already achieves the minimum row count for that case, and the
 * bands are time-sorted when they arrive here.
 */
export const laneRows = (bands: readonly TimelineBand[]): readonly Lane[] => {
  const byType = new Map<string, TimelineBand[]>()
  for (const band of bands) {
    const existing = byType.get(band.entityType)
    if (existing === undefined) byType.set(band.entityType, [band])
    else existing.push(band)
  }

  return [...byType].map(([entityType, laneBands]) => {
    // The instant each row is free from. A band goes on the first row whose
    // last occupant has already ended.
    const rowEnds: number[] = []
    const positioned = laneBands.map((band) => {
      const start = startOf(band)
      // `<=`, not `<`: the intervals are half-open, so a band beginning
      // exactly where the previous one ended shares no instant with it.
      // Treating touching as overlapping would put every consecutive
      // year-precision pair on its own row, drawing a diagonal line.
      const row = rowEnds.findIndex((freeFrom) => freeFrom <= start)
      if (row === -1) {
        rowEnds.push(endOf(band))
        return { band, row: rowEnds.length - 1 }
      }
      rowEnds[row] = endOf(band)
      return { band, row }
    })
    return { entityType, rows: Math.max(rowEnds.length, 1), bands: positioned }
  })
}

/** The axis extent: earliest bounded start to latest bounded end, or `null`
 *  when nothing is bounded.
 *
 * Open bounds contribute nothing, because an axis cannot begin at negative
 * infinity. A band open below is drawn running off the edge of the span the
 * bounded bands establish, which is the only rendering of "unbounded" that
 * does not require inventing a date.
 */
export const spanOf = (bands: readonly TimelineBand[]): { from: number; to: number } | null => {
  const starts = bands.map(startOf).filter(Number.isFinite)
  const ends = bands.map(endOf).filter(Number.isFinite)
  if (starts.length === 0 && ends.length === 0) return null
  return { from: Math.min(...starts, ...ends), to: Math.max(...starts, ...ends) }
}
