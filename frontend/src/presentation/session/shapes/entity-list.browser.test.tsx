import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { EntityList } from './EntityList.tsx'
import { tenEntities } from './fixtures.ts'

/** The property that makes a bar mean anything, measured.
 *
 * A multi-column grid was tried and rejected because each column carries its
 * own bar baseline: two bars side by side are then *not* on a common scale,
 * and the layout invites a comparison that is wrong. One column puts every bar
 * on one axis — which is a claim about laid-out geometry, so jsdom cannot
 * judge it. There every rect is zero and every one of these assertions would
 * pass against a stylesheet that had been deleted.
 */
describe('EntityList geometry', () => {
  it('puts every bar on one axis', () => {
    const { getAllByTestId } = render(<EntityList artifact={tenEntities} phase="settled" />)
    const tracks = getAllByTestId('bar').map((node) => node.getBoundingClientRect())
    expect(tracks.length).toBeGreaterThan(1)
    expect(new Set(tracks.map((box) => Math.round(box.left))).size).toBe(1)
    expect(new Set(tracks.map((box) => Math.round(box.width))).size).toBe(1)
  })

  it('draws each fill in proportion to its value', () => {
    // The counts run 10, 9, 8 … so the second fill is nine tenths of the
    // first. This is the half a shared track cannot show: aligned columns say
    // the list is one axis, and only the fills say the numbers are drawn.
    const { getAllByTestId } = render(<EntityList artifact={tenEntities} phase="settled" />)
    const fills = getAllByTestId('bar-fill').map((node) => node.getBoundingClientRect())
    expect(fills[1]!.width / fills[0]!.width).toBeCloseTo(9 / 10, 1)
    expect(fills[4]!.width / fills[0]!.width).toBeCloseTo(6 / 10, 1)
  })

  it('keeps the value column aligned down the whole list', () => {
    // The third column is what a reader's eye runs down. A per-row width would
    // make the counts stagger, which reads as noise rather than as a column.
    const { getAllByTestId } = render(<EntityList artifact={tenEntities} phase="settled" />)
    const values = getAllByTestId('entity').map((row) =>
      row.querySelector('[data-testid="stream-value"]')!.getBoundingClientRect(),
    )
    expect(new Set(values.map((box) => Math.round(box.right))).size).toBe(1)
  })
})
