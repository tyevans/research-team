import { useMemo } from 'react'

import type { GraphView } from '@domain/knowledge/graph.ts'

import { colorForType, KIND_TOKENS } from './entity-colors.ts'

/** What the colours and the two node shapes on the canvas mean.
 *
 * The drawing already carried both facts -- a node's colour is its entity
 * type, and a hollow node has a neighbourhood nobody has pulled in yet -- and
 * neither was written down anywhere. A reader could see that some dots were
 * blue and some were green without any way to learn which was a `fact` and
 * which a `hypothesis`, so the colour was decoration rather than information.
 *
 * Built from the drawn nodes rather than from every type in the corpus: this
 * is a key to the picture on screen, and listing types that are not in it
 * would be a glossary instead.
 */
export const GraphLegend = ({ view }: { view: GraphView }) => {
  const palette = useMemo(() => {
    const styles = getComputedStyle(document.documentElement)
    return KIND_TOKENS.map((name) => styles.getPropertyValue(name).trim() || '#6ba7f5')
  }, [])

  const types = useMemo(() => {
    const counts = new Map<string, number>()
    for (const node of view.nodes) {
      counts.set(node.entityType, (counts.get(node.entityType) ?? 0) + 1)
    }
    // Commonest first: the type a reader is looking at most of is the one
    // worth naming first, and alphabetical order would bury it under whatever
    // happened to start with an `a`.
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  }, [view.nodes])

  if (types.length === 0) return null

  return (
    <aside className="graph-legend" aria-label="What the canvas colours mean">
      <ul className="graph-legend-types">
        {types.map(([type, count]) => (
          <li key={type} className="graph-legend-row">
            <span
              className="graph-legend-swatch"
              style={{ background: colorForType(type, palette) }}
              aria-hidden="true"
            />
            <span className="graph-legend-name">{type}</span>
            <span className="graph-legend-count">{count}</span>
          </li>
        ))}
      </ul>
      {/* The shape rule, in the one place somebody would look for it. Worth a
          line of prose rather than a second swatch column: it is a rule about
          what to do next -- click the hollow ones -- not another category.
          Withheld when there are none: on a graph drawn whole every node is
          filled, and a key explaining a shape that is not on the canvas sends
          the reader hunting for one. */}
      {view.nodes.some((node) => !view.expanded.has(node.id)) ? (
        <p className="graph-legend-note">
          Hollow nodes have more to pull in. Click one to expand it.
        </p>
      ) : null}
      {/* A sibling of the note above, on the same terms: prose rather than a
          swatch, because a dashed line is a rule about where an edge came
          from, not another category to swatch alongside entity types. And
          withheld the same way, when the drawn graph has no inferred edge --
          otherwise this key would explain a mark nobody can see. */}
      {view.links.some((link) => link.inferred) ? (
        <p className="graph-legend-note">
          Dashed edges are inferred from dates, not asserted by a document. Hover one to see the
          arithmetic.
        </p>
      ) : null}
    </aside>
  )
}
