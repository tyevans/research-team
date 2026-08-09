import { act, render } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

import type { GraphNode, GraphView } from '@domain/knowledge/graph.ts'

// `react-force-graph-2d` itself is mocked, not this module -- this is the
// one test that renders the real `GraphCanvas`, since the reheat-while-
// typing bug lives inside it: a re-render handing the underlying library a
// new `graphData` object re-ingests the data and restarts the simulation,
// and only a component-level test can see that object's identity.
let receivedGraphData: unknown
let receivedOnNodeClick: ((node: unknown) => void) | undefined
let receivedOnEngineStop: (() => void) | undefined
let receivedWidth: number | undefined

/** The handful of imperative methods `GraphCanvas` drives the library
 *  through, recorded rather than performed. `zoom()` with no argument is the
 *  library's getter; the component reads it to avoid zooming out, so the fake
 *  has to answer as well as record. */
const api = {
  centerAt: vi.fn(),
  zoom: vi.fn((scale?: number) => (scale === undefined ? currentZoom : undefined)),
  zoomToFit: vi.fn(),
}
let currentZoom = 1

vi.mock('react-force-graph-2d', () => ({
  default: (props: {
    graphData: unknown
    onNodeClick: (node: unknown) => void
    onEngineStop?: () => void
    width?: number
    // React 19 passes `ref` as an ordinary prop to function components, which
    // is how this stands in for the real component's imperative handle.
    ref?: { current: unknown }
  }) => {
    receivedGraphData = props.graphData
    receivedOnNodeClick = props.onNodeClick
    receivedOnEngineStop = props.onEngineStop
    receivedWidth = props.width
    if (props.ref) props.ref.current = api
    return null
  },
}))

const { GraphCanvas } = await import('./GraphCanvas.tsx')

const view = (): GraphView => ({
  nodes: [{ id: 'ada', name: 'Ada Lovelace', entityType: 'Person' }],
  links: [],
  expanded: new Set(),
})

/** A node carrying the `x`/`y` d3-force writes onto it during the
 *  simulation's first tick -- the state every node is in by the time a reader
 *  can click one. The cast is the point: `GraphNode` does not declare those
 *  fields precisely because they are the library's, written in place onto the
 *  objects this app hands it. */
const positioned = (id: string, name: string, x: number, y: number): GraphNode =>
  ({ id, name, entityType: 'Person', x, y }) as unknown as GraphNode

const settledView = (): GraphView => ({
  nodes: [
    positioned('ada', 'Ada Lovelace', 30, -12),
    positioned('babbage', 'Charles Babbage', -8, 40),
  ],
  links: [],
  expanded: new Set(),
})

beforeEach(() => {
  currentZoom = 1
  api.centerAt.mockClear()
  api.zoom.mockClear()
  api.zoomToFit.mockClear()
})

it('hands react-force-graph-2d the same graphData object across a re-render that leaves the view unchanged', () => {
  const same = view()
  const { rerender } = render(<GraphCanvas view={same} selected={null} onNodeClick={() => {}} />)
  const first = receivedGraphData

  // A re-render that changes only an unrelated prop (`onNodeClick`, as a
  // fresh search-box keystroke would produce in `GraphPane`) must not hand
  // the library a new `graphData` object -- that object identity, not the
  // node objects inside it, is what react-force-graph-2d checks to decide
  // whether to reheat its d3-force simulation.
  rerender(<GraphCanvas view={same} selected={null} onNodeClick={() => {}} />)
  const second = receivedGraphData

  expect(second).toBe(first)
})

it('sizes the canvas to its container rather than letting it default to the window', () => {
  // force-graph defaults `width` to `window.innerWidth`. The graph sits in one
  // column of a two-column grid, so that default draws a canvas several times
  // the pane's width and centres the simulation at `width / 2` -- far to the
  // right of anything the reader can see. Passing a measured width is what
  // puts the drawing where the pane is.
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(480)

  render(<GraphCanvas view={view()} selected={null} onNodeClick={() => {}} />)

  expect(receivedWidth).toBe(480)
})

it('pins a clicked node at its simulated position so it does not drift while its neighbourhood settles', () => {
  render(<GraphCanvas view={view()} selected={null} onNodeClick={() => {}} />)

  // Stand-in for the node object `react-force-graph-2d` would hand back --
  // the simulation has already written x/y onto it by the time a click
  // fires.
  const node = { id: 'ada', x: 12, y: -4 }
  receivedOnNodeClick?.(node)

  expect(node).toMatchObject({ fx: 12, fy: -4 })
})

it('centres the view on a selected node, so the reader does not have to find it', () => {
  // Selecting used to ring a dot and leave the view where it was, which on a
  // graph drawn whole means a ringed dot somewhere in a field of hundreds.
  const drawn = settledView()
  const { rerender } = render(<GraphCanvas view={drawn} selected={null} onNodeClick={() => {}} />)

  rerender(<GraphCanvas view={drawn} selected="babbage" onNodeClick={() => {}} />)

  expect(api.centerAt).toHaveBeenCalledWith(-8, 40, expect.any(Number))
})

it('zooms in far enough to read the node it centred on', () => {
  const drawn = settledView()
  const { rerender } = render(<GraphCanvas view={drawn} selected={null} onNodeClick={() => {}} />)

  rerender(<GraphCanvas view={drawn} selected="ada" onNodeClick={() => {}} />)

  const [scale] = api.zoom.mock.calls.find(([argument]) => argument !== undefined) ?? []
  expect(scale).toBeGreaterThan(1)
})

it('never zooms out to reach the focus level', () => {
  // On a small graph the fitted view is already closer than the focus zoom,
  // and pulling back as the reward for clicking something is the opposite of
  // what was asked for.
  currentZoom = 8
  const drawn = settledView()
  const { rerender } = render(<GraphCanvas view={drawn} selected={null} onNodeClick={() => {}} />)

  rerender(<GraphCanvas view={drawn} selected="ada" onNodeClick={() => {}} />)

  const [scale] = api.zoom.mock.calls.find(([argument]) => argument !== undefined) ?? []
  expect(scale).toBe(8)
})

it('centres an entity selected before the simulation has positioned anything', () => {
  // A pasted `/entity/<id>` link selects a node that has no x/y yet, so the
  // move cannot happen when it is asked for -- only once the graph settles.
  const unpositioned = view()
  const ada = unpositioned.nodes[0] as GraphNode
  render(<GraphCanvas view={unpositioned} selected="ada" onNodeClick={() => {}} />)

  expect(api.centerAt).not.toHaveBeenCalled()

  // The same node object, now carrying the position d3-force wrote onto it in
  // place -- which is the state the library's own nodes are in by the time
  // `onEngineStop` fires.
  Object.assign(ada, { x: 5, y: 6 })
  act(() => receivedOnEngineStop?.())

  expect(api.centerAt).toHaveBeenCalledWith(5, 6, expect.any(Number))
  // And it frames the node rather than the whole graph: the reader asked for
  // one entity, not for an overview with that entity somewhere in it.
  expect(api.zoomToFit).not.toHaveBeenCalled()
})

it('does not re-frame the whole graph while a node is selected', () => {
  // Expanding a selection settles the simulation again. Fitting then would
  // zoom straight back out from the node just clicked, undoing the move a
  // moment after it finished.
  const drawn = settledView()
  const { rerender } = render(<GraphCanvas view={drawn} selected="ada" onNodeClick={() => {}} />)
  act(() => receivedOnEngineStop?.())
  api.centerAt.mockClear()

  const grown: GraphView = {
    ...drawn,
    nodes: [...drawn.nodes, { id: 'c', name: 'C', entityType: 'Person' }],
  }
  rerender(<GraphCanvas view={grown} selected="ada" onNodeClick={() => {}} />)
  act(() => receivedOnEngineStop?.())

  expect(api.zoomToFit).not.toHaveBeenCalled()
})

it('still frames the whole graph when nothing is selected', () => {
  render(<GraphCanvas view={settledView()} selected={null} onNodeClick={() => {}} />)

  act(() => receivedOnEngineStop?.())

  expect(api.zoomToFit).toHaveBeenCalled()
})

it('does not repeat the move for a selection it has already made', () => {
  const drawn = settledView()
  const { rerender } = render(<GraphCanvas view={drawn} selected="ada" onNodeClick={() => {}} />)
  expect(api.centerAt).toHaveBeenCalledTimes(1)

  // An unrelated prop change, as a keystroke in the search box above produces.
  rerender(<GraphCanvas view={drawn} selected="ada" onNodeClick={() => {}} />)

  expect(api.centerAt).toHaveBeenCalledTimes(1)
})
