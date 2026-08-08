import { memo, useMemo } from 'react'
import ForceGraph2D from 'react-force-graph-2d'

import type { GraphView } from '@domain/knowledge/graph.ts'

/** A node as `react-force-graph-2d` hands it back once its simulation has
 *  positioned it: the `GraphNode` fields, plus the `x`/`y` the simulation
 *  wrote in and the `fx`/`fy` it will read to pin a node in place. */
interface SimulatedNode {
  id: string
  x?: number
  y?: number
  fx?: number
  fy?: number
}

/** The force-directed drawing of a `GraphView`. The only module in this
 *  console that imports `react-force-graph-2d` -- `GraphPane` loads this
 *  one lazily, so the ~60 kB canvas/d3-force bundle is fetched only when a
 *  reader actually opens the research page's graph pane, never as part of
 *  rendering a session transcript.
 *
 * `graphData` is memoised on `view` rather than rebuilt every render.
 * `expand`'s node-identity guarantee (existing nodes keep their object
 * reference) means the underlying d3-force simulation keeps each node's
 * `x`/`y` regardless of whether `graphData` is a fresh object -- but
 * `react-force-graph-2d` re-ingests and reheats its simulation whenever the
 * `graphData` *object itself* changes identity, independently of whether
 * the nodes inside it did. `GraphPane` re-renders on every keystroke in its
 * search box (typing changes `results`/`searching`, not `view`), so without
 * this memo the graph would reheat and visibly shake while a reader typed,
 * even though nothing about the drawn graph had changed.
 */
export const GraphCanvas = memo(function GraphCanvas({
  view,
  onNodeClick,
}: {
  view: GraphView
  onNodeClick: (id: string) => void
}) {
  const graphData = useMemo(() => ({ nodes: [...view.nodes], links: [...view.links] }), [view])

  return (
    <ForceGraph2D
      graphData={graphData}
      nodeLabel={(node) => `${String(node.name)} (${String(node.entityType)})`}
      linkLabel={(link) => String(link.relationshipType)}
      linkDirectionalArrowLength={4}
      height={360}
      onNodeClick={(node) => {
        // Pin the focused node at its current simulated position so it
        // stays put while the neighbourhood pulled in around it settles --
        // without this, expanding a node lets the whole graph drift, since
        // nothing anchors the point the reader is actually looking at.
        const pinned = node as SimulatedNode
        if (pinned.x !== undefined) pinned.fx = pinned.x
        if (pinned.y !== undefined) pinned.fy = pinned.y
        onNodeClick(String(node.id))
      }}
    />
  )
})
