import ForceGraph2D from 'react-force-graph-2d'

import type { GraphView } from '@domain/knowledge/graph.ts'

/** The force-directed drawing of a `GraphView`. The only module in this
 *  console that imports `react-force-graph-2d` -- `GraphPane` loads this
 *  one lazily, so the ~60 kB canvas/d3-force bundle is fetched only when a
 *  reader actually opens the research page's graph pane, never as part of
 *  rendering a session transcript.
 *
 * `graphData` is handed the store's `view.nodes`/`view.links` arrays
 * directly rather than copies: `expand`'s node-identity guarantee is what
 * lets the underlying d3-force simulation keep each node's `x`/`y` across a
 * re-render, and a copy here would throw that away on every click.
 */
export const GraphCanvas = ({
  view,
  onNodeClick,
}: {
  view: GraphView
  onNodeClick: (id: string) => void
}) => (
  <ForceGraph2D
    graphData={{ nodes: [...view.nodes], links: [...view.links] }}
    nodeLabel={(node) => `${String(node.name)} (${String(node.entityType)})`}
    linkLabel={(link) => String(link.relationshipType)}
    linkDirectionalArrowLength={4}
    height={360}
    onNodeClick={(node) => onNodeClick(String(node.id))}
  />
)
