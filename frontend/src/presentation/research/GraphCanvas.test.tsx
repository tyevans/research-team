import { render } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import type { GraphView } from '@domain/knowledge/graph.ts'

// `react-force-graph-2d` itself is mocked, not this module -- this is the
// one test that renders the real `GraphCanvas`, since the reheat-while-
// typing bug lives inside it: a re-render handing the underlying library a
// new `graphData` object re-ingests the data and restarts the simulation,
// and only a component-level test can see that object's identity.
let receivedGraphData: unknown
let receivedOnNodeClick: ((node: unknown) => void) | undefined
vi.mock('react-force-graph-2d', () => ({
  default: (props: { graphData: unknown; onNodeClick: (node: unknown) => void }) => {
    receivedGraphData = props.graphData
    receivedOnNodeClick = props.onNodeClick
    return null
  },
}))

const { GraphCanvas } = await import('./GraphCanvas.tsx')

const view = (): GraphView => ({
  nodes: [{ id: 'ada', name: 'Ada Lovelace', entityType: 'Person' }],
  links: [],
  expanded: new Set(),
})

it('hands react-force-graph-2d the same graphData object across a re-render that leaves the view unchanged', () => {
  const same = view()
  const { rerender } = render(<GraphCanvas view={same} onNodeClick={() => {}} />)
  const first = receivedGraphData

  // A re-render that changes only an unrelated prop (`onNodeClick`, as a
  // fresh search-box keystroke would produce in `GraphPane`) must not hand
  // the library a new `graphData` object -- that object identity, not the
  // node objects inside it, is what react-force-graph-2d checks to decide
  // whether to reheat its d3-force simulation.
  rerender(<GraphCanvas view={same} onNodeClick={() => {}} />)
  const second = receivedGraphData

  expect(second).toBe(first)
})

it('pins a clicked node at its simulated position so it does not drift while its neighbourhood settles', () => {
  render(<GraphCanvas view={view()} onNodeClick={() => {}} />)

  // Stand-in for the node object `react-force-graph-2d` would hand back --
  // the simulation has already written x/y onto it by the time a click
  // fires.
  const node = { id: 'ada', x: 12, y: -4 }
  receivedOnNodeClick?.(node)

  expect(node).toMatchObject({ fx: 12, fy: -4 })
})
