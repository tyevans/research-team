import { describe, expect, it } from 'vitest'

import {
  framing,
  MAX_FIT_ZOOM,
  MIN_FIT_ZOOM,
  NODE_RADIUS_FAR,
  NODE_RADIUS_NEAR,
  nodeRadius,
} from './graph-framing.ts'

const box = (x0: number, x1: number, y0: number, y1: number) => ({
  x: [x0, x1] as const,
  y: [y0, y1] as const,
})

describe('framing', () => {
  it('centres on the middle of the box', () => {
    const frame = framing(box(-100, 300, 0, 200), 900, 600, 48)
    expect(frame).not.toBeNull()
    expect(frame?.x).toBe(100)
    expect(frame?.y).toBe(100)
  })

  it('fits by the tighter of the two axes', () => {
    // 804 usable width over a 400-wide box is 2.01; 504 usable height over a
    // 200-tall box is 2.52. The width is the constraint, and 2.01 is under the
    // ceiling, so it is the answer unchanged.
    expect(framing(box(-200, 200, -100, 100), 900, 600, 48)?.zoom).toBeCloseTo(2.01)
  })

  it('refuses to zoom closer than the ceiling on a graph too small to fill the stage', () => {
    // The regression this module exists for. A single node's bounding box is
    // its own radius, and `force-graph`'s `zoomToFit` divides the stage by it:
    // measured at 50.4x in Chromium at 900x600. Reverting the clamp in
    // `framing` makes this read 50.4.
    expect(framing(box(-5, 5, -5, 5), 900, 600, 48)?.zoom).toBe(MAX_FIT_ZOOM)
  })

  it('treats a graph settled in a straight line as unconstrained on that axis', () => {
    // Zero height, so `usableHeight / 0` is Infinity and only the width
    // constrains. Not a defensive branch: three nodes in a row is an ordinary
    // settled layout, and Infinity reaching `zoom()` blanks the canvas.
    const frame = framing(box(-1000, 1000, 50, 50), 900, 600, 48)
    expect(frame?.zoom).toBeCloseTo(804 / 2000)
    expect(frame?.y).toBe(50)
  })

  it('answers the ceiling for a box with no extent at all', () => {
    // 0/0 is NaN, which `Math.min`/`Math.max` propagate rather than clamp.
    expect(framing(box(7, 7, 7, 7), 900, 600, 48)?.zoom).toBe(MAX_FIT_ZOOM)
  })

  it('clips rather than pulling back past the floor', () => {
    expect(framing(box(-1e6, 1e6, -1e6, 1e6), 900, 600, 48)?.zoom).toBe(MIN_FIT_ZOOM)
  })

  it('declines to move the view when the stage has no room left after padding', () => {
    expect(framing(box(-10, 10, -10, 10), 80, 600, 48)).toBeNull()
  })

  it('declines to move the view for a simulation that has not positioned anything', () => {
    expect(framing(box(NaN, NaN, NaN, NaN), 900, 600, 48)).toBeNull()
  })
})

describe('nodeRadius', () => {
  it('draws the largest mark for a graph of one', () => {
    expect(nodeRadius(1)).toBe(NODE_RADIUS_NEAR)
    expect(nodeRadius(0)).toBe(NODE_RADIUS_NEAR)
  })

  it('shrinks monotonically as the graph fills up', () => {
    const sizes = [1, 5, 20, 100, 400, 1700].map(nodeRadius)
    for (let i = 1; i < sizes.length; i += 1) {
      expect(sizes[i]).toBeLessThanOrEqual(sizes[i - 1] as number)
    }
  })

  it('bottoms out rather than vanishing on the largest graph the cap allows', () => {
    expect(nodeRadius(400)).toBeCloseTo(NODE_RADIUS_FAR)
    expect(nodeRadius(5000)).toBe(NODE_RADIUS_FAR)
  })

  it('spends most of its travel on the small graphs, which is the point of the log', () => {
    // Half the ramp is used up by 20 nodes. A linear ramp to 400 would have
    // moved 5% by then, which is invisible -- and the graphs that look broken
    // are the ones with a handful of nodes.
    expect(nodeRadius(20)).toBeLessThan(8)
    expect(nodeRadius(20)).toBeGreaterThan(NODE_RADIUS_FAR)
  })
})
