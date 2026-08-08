import { edgesOf, type GraphView } from '@domain/knowledge/graph.ts'

/** What the selected node is, and what it is connected to.
 *
 * The answer to "I clicked a node and nothing meaningful happened". Expanding
 * draws more dots; this says what the dot under the cursor actually was and
 * how it relates to the ones around it -- which is the question somebody
 * browsing a knowledge graph is asking in the first place.
 *
 * Relationship type is the row's heading rather than a detail hidden in a
 * tooltip: `advised` and `contradicts` are the content of a knowledge graph,
 * and a list that only said "connected to" would be throwing away the part
 * worth reading.
 */
export const GraphDetail = ({
  view,
  selected,
  onSelect,
  onClose,
}: {
  view: GraphView
  selected: string
  /** Selecting from here expands too, which is what makes this a way of
   *  walking the graph rather than a read-only card. */
  onSelect: (id: string) => void
  onClose: () => void
}) => {
  const node = view.nodes.find((candidate) => candidate.id === selected)
  // The selection can outlive its node only if something removed it from the
  // view, which nothing does today -- but rendering an empty shell would be a
  // worse answer than rendering nothing.
  if (!node) return null

  const edges = edgesOf(view, selected)

  return (
    <aside className="graph-detail" aria-label={`About ${node.name}`}>
      <header className="graph-detail-head">
        <div className="graph-detail-heading">
          <h3 className="graph-detail-name">{node.name}</h3>
          <p className="graph-detail-type">{node.entityType}</p>
        </div>
        <button
          type="button"
          className="btn btn-sm"
          onClick={onClose}
          aria-label="Close entity details"
        >
          Close
        </button>
      </header>

      {edges.length === 0 ? (
        <p className="graph-detail-empty">
          Nothing connected to this one has been drawn yet. Click it on the canvas to pull in its
          neighbourhood.
        </p>
      ) : (
        <ul className="graph-detail-edges">
          {edges.map((edge) => (
            <li key={`${edge.direction}|${edge.relationshipType}|${edge.other.id}`}>
              <button
                type="button"
                className="graph-detail-edge"
                onClick={() => onSelect(edge.other.id)}
              >
                <span className="graph-detail-rel">
                  {/* The arrow carries the direction, so the row reads as a
                      sentence about the selected node in both cases rather
                      than as a label the reader has to reverse in their head
                      half the time. */}
                  {edge.direction === 'out' ? '→' : '←'} {edge.relationshipType}
                </span>
                <span className="graph-detail-other">{edge.other.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}
