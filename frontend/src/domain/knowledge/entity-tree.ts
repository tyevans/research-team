/** The knowledge graph's entities, grouped for reading rather than for drawing.
 *
 * A pure fold, the same shape and for the same reason as `graph.ts` beside it:
 * the sorting and the empty-group rule are the parts with a correctness story,
 * and they are worth holding somewhere no React render can reach.
 */

import type { GraphNode } from './graph.ts'

/** One type's entities. There is no empty group: a group exists because an
 *  entity landed in it, which is what keeps a filter from leaving a screen of
 *  headings that open onto nothing. */
export interface EntityGroup {
  readonly entityType: string
  readonly entities: readonly GraphNode[]
}

/** Group entities by type, optionally narrowed to a substring of their names.
 *
 * **Filtering happens before grouping**, and that ordering is the contract:
 * done the other way, a type with no matching entity would keep its heading
 * and its count would disagree with what opening it showed.
 *
 * `localeCompare` rather than `<` in both sorts. A code-point comparison puts
 * `Ångström` after `Zeta`, which is wrong in the only sense that matters here
 * -- the list exists to be scanned by a person. The cost is a slower sort on a
 * capped node set, which is not a size where it shows.
 *
 * Ties keep input order: `Array.prototype.sort` is required to be stable, so
 * two entities with the same name stay in the order the server sent them
 * rather than being scrambled by the client.
 */
export const groupByType = (
  nodes: readonly GraphNode[],
  filter?: string,
): readonly EntityGroup[] => {
  const needle = (filter ?? '').trim().toLowerCase()
  const matching =
    needle === '' ? nodes : nodes.filter((node) => node.name.toLowerCase().includes(needle))

  const byType = new Map<string, GraphNode[]>()
  for (const node of matching) {
    const existing = byType.get(node.entityType)
    if (existing) existing.push(node)
    else byType.set(node.entityType, [node])
  }

  return [...byType.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([entityType, entities]) => ({
      entityType,
      entities: [...entities].sort((left, right) => left.name.localeCompare(right.name)),
    }))
}
