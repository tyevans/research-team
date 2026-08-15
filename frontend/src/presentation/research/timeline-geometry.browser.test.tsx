import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { TimelineBand } from '@domain/knowledge/timeline.ts'

import { TimelineCanvas } from './TimelineCanvas.tsx'

/** Geometry, in a browser, because jsdom has none.
 *
 * Every assertion here is a measurement: `getBoundingClientRect` on a laid-out
 * SVG. In jsdom each one returns 0 and would have to be written as a comment,
 * which `CLAUDE.md` records happening four times in a row before this suite
 * existed.
 */

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

const rectFor = (id: string) =>
  document.querySelector(`[data-band="${id}"]`)!.getBoundingClientRect()

describe('timeline geometry', () => {
  it('draws a band twice as wide as one covering half its span', () => {
    // The proportionality the axis is for. Asserted as a ratio rather than an
    // absolute width because the viewport is fixed in `vite.config.ts` and an
    // absolute would break the day anybody changed it -- for a reason having
    // nothing to do with this drawing.
    render(
      <TimelineCanvas
        bands={[year('wide', 1800, 1900), year('narrow', 1900, 1950)]}
        selected={null}
        onSelect={() => {}}
      />,
    )

    expect(rectFor('wide').width / rectFor('narrow').width).toBeCloseTo(2, 1)
  })

  it('puts two bands that overlap in time at different heights', () => {
    // `timeline.test.ts` already asserts they get different row *numbers*.
    // This asserts the row number reaches the drawing -- the two are different
    // claims, and the fold being right while the rendering ignores it is
    // exactly the failure a green jsdom suite would not catch.
    render(
      <TimelineCanvas
        bands={[year('early', 1800, 1850), year('late', 1820, 1870)]}
        selected={null}
        onSelect={() => {}}
      />,
    )

    expect(rectFor('early').top).not.toBeCloseTo(rectFor('late').top, 0)
  })

  it('gives every band a non-zero width, including an instant', () => {
    // A zero-width rect is invisible and unclickable, and an entity that
    // vanishes at some zoom levels reads as data that is missing.
    render(
      <TimelineCanvas
        bands={[year('instant', 1815, 1815), year('span', 1800, 1900)]}
        selected={null}
        onSelect={() => {}}
      />,
    )

    expect(rectFor('instant').width).toBeGreaterThan(0)
  })

  it('separates lanes vertically by entity type', () => {
    render(
      <TimelineCanvas
        bands={[year('a', 1800, 1810, 'person'), year('b', 1800, 1810, 'event')]}
        selected={null}
        onSelect={() => {}}
      />,
    )

    // Same interval, different types: any vertical separation between them is
    // the lane grouping, since the packing would have put them on one row.
    expect(rectFor('a').top).not.toBeCloseTo(rectFor('b').top, 0)
  })

  it('strokes a selected band in the accent colour and an unselected one not at all', () => {
    // The defect this is shaped after: a chosen control drawing in the
    // unchosen colour shipped past a fully green suite and was caught by eye.
    // Both halves asserted, because a canvas that stroked everything would
    // satisfy the first.
    render(
      <TimelineCanvas
        bands={[year('chosen', 1800, 1810), year('other', 1820, 1830)]}
        selected="chosen"
        onSelect={() => {}}
      />,
    )

    const strokeOf = (id: string) =>
      getComputedStyle(document.querySelector(`[data-band="${id}"]`)!).stroke

    expect(strokeOf('chosen')).not.toBe(strokeOf('other'))
    expect(strokeOf('chosen')).not.toBe('none')
  })
})
