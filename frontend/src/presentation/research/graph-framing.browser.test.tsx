import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import type { GraphLink, GraphNode, GraphView } from '@domain/knowledge/graph.ts'

import { GraphCanvas } from './GraphCanvas.tsx'
import { MAX_FIT_ZOOM, MIN_FIT_ZOOM } from './graph-framing.ts'

/** That `GraphCanvas` *applies* `framing` -- which `graph-framing.test.ts`
 *  already pins the arithmetic of, and which no jsdom test can reach.
 *
 * jsdom has no layout, so the `ResizeObserver` measurement the canvas withholds
 * rendering on never lands, `force-graph` is never handed a size, and no
 * simulation runs. Every number below would be the initial value of a canvas
 * that was never drawn.
 *
 * **Proved red.** Against `zoomToFit(400, 48)` -- the call this replaced -- the
 * single-node case measured **50.4x**, which is `(600 - 96) / 10`: one node's
 * bounding box is its own 5px radius, and the library's fit has no ceiling.
 * That defect is invisible to the eye, because every mark this canvas paints is
 * divided by the zoom. What it costs the reader is the gesture afterwards: a
 * scroll-wheel notch out of 50x moves nothing, and "Reset view" hands back the
 * same useless frame.
 */

const node = (id: string, i = 0): GraphNode => ({
  id,
  name: `Entity ${id}`,
  entityType: ['Person', 'Place', 'Event', 'Organisation'][i % 4] ?? 'Person',
})

const view = (nodes: readonly GraphNode[], links: readonly GraphLink[] = []): GraphView => ({
  nodes,
  links,
  expanded: new Set<string>(),
})

const nodes = (count: number) =>
  Array.from({ length: count }, (_, index) => node(`n${String(index)}`, index))

const chain = (count: number): GraphLink[] =>
  Array.from({ length: count - 1 }, (_, index) => ({
    source: `n${String(index)}`,
    target: `n${String(index + 1)}`,
    relationshipType: 'knew',
  }))

/** `force-graph` attaches its d3-zoom to the `<canvas>` (`state.zoom.__baseElem
 *  = select(state.canvas)`) and reads the current zoom back off it with
 *  `zoomTransform(state.canvas)`. d3 stores that transform on the element as
 *  `__zoom`, so the view's real position is already in the DOM and this file
 *  needs no test-only prop on the component to see it. */
const transform = (host: HTMLElement): { k: number; x: number; y: number } => {
  const canvas = host.querySelector('canvas')
  if (!canvas) throw new Error('the canvas never rendered')
  return (canvas as unknown as { __zoom: { k: number; x: number; y: number } }).__zoom
}

/** The simulation's `cooldownTime` is 1800ms and the framing transition is
 *  400ms on top of it; this is that with room to spare on a loaded machine. */
const SETTLE_MS = 4000

const settled = async (content: React.ReactNode) => {
  const screen = await render(
    <div className="relative" style={{ width: '900px', height: '600px' }}>
      {content}
    </div>,
  )
  const host = screen.container
  await expect.poll(() => host.querySelector('canvas') !== null, { timeout: SETTLE_MS }).toBe(true)
  await new Promise((resolve) => setTimeout(resolve, SETTLE_MS))
  return host
}

const alone = <GraphCanvas view={view([node('only')])} selected={null} onNodeClick={() => {}} />

it('frames a single node at reading distance rather than fifty times into it', async () => {
  const host = await settled(alone)

  expect(transform(host).k).toBe(MAX_FIT_ZOOM)
})

it('centres the one node it has on the canvas it was given', async () => {
  const host = await settled(alone)

  // The node settles at the origin (`force-graph` runs a `forceCenter`), so its
  // screen position is the transform's translation -- and a correct framing
  // puts that at the middle of the measured canvas. Asserted because the fit
  // and the centre are computed together in `framing`, and a wrong bounding box
  // would move one without the other: an off-centre single node is the same
  // visual symptom as a bad fit and would be indistinguishable from it by eye.
  const canvas = host.querySelector('canvas') as HTMLCanvasElement
  const box = canvas.getBoundingClientRect()
  const { x, y } = transform(host)
  expect(x).toBeCloseTo(box.width / 2, 0)
  expect(y).toBeCloseTo(box.height / 2, 0)
})

it('pulls back to fit a linked graph, and no further than the floor', async () => {
  const host = await settled(
    <GraphCanvas view={view(nodes(60), chain(60))} selected={null} onNodeClick={() => {}} />,
  )

  const { k } = transform(host)
  expect(k).toBeGreaterThanOrEqual(MIN_FIT_ZOOM)
  expect(k).toBeLessThan(MAX_FIT_ZOOM)
})

it('fits a sparse thousand-node cloud inside the stage', async () => {
  // The shape the "Ancient Rome" project is actually in: many entities, almost
  // no edges among them. The fit is small -- labels stop below 0.7 and this is
  // well under -- but it is on screen and bounded, which is the whole ask.
  const host = await settled(
    <GraphCanvas view={view(nodes(1000))} selected={null} onNodeClick={() => {}} />,
  )

  const { k } = transform(host)
  expect(k).toBeGreaterThanOrEqual(MIN_FIT_ZOOM)
  expect(k).toBeLessThan(1)
})
