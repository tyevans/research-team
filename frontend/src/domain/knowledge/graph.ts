/** The knowledge graph as displayed, and how a fetched neighbourhood merges into it.
 *
 * This module is a pure fold: no fetching, no React, no store. Those arrive
 * in a later task; this one only owns the merge semantics, because those
 * semantics have a correctness property (node identity, below) that is easy
 * to get wrong under refactoring pressure from the caller.
 */

export interface GraphNode {
  readonly id: string
  readonly name: string
  readonly entityType: string
}

export interface GraphLink {
  readonly source: string
  readonly target: string
  readonly relationshipType: string
}

/** A page of entity-search results, plus whether the server held more back.
 *
 * The route paginates (`limit` defaults to 100, `next_after` carries a
 * cursor), but the browser does not page -- it shows one screen of results.
 * `truncated` is what keeps that silent: a search matching 150 entities
 * must say it showed only the first 100, not just show 100 and stop.
 */
export interface EntitySearchResult {
  readonly entities: readonly GraphNode[]
  readonly truncated: boolean
}

/** What the backend's neighbourhood route returns: a root entity, the
 *  entities reachable from it, and the relationships among them.
 *
 * The root is *not* repeated inside `entities` -- it arrives in its own field
 * and nowhere else, which is what `GraphReadPort.neighborhood` documents on
 * the other side of the wire. A merge that reads only `entities` therefore
 * draws the root's edges without drawing the root.
 */
export interface Neighborhood {
  readonly root: GraphNode
  readonly entities: readonly GraphNode[]
  readonly relationships: readonly GraphLink[]
}

export interface GraphView {
  readonly nodes: readonly GraphNode[]
  readonly links: readonly GraphLink[]
  /** Node ids whose neighbourhood has already been fetched, so a second
   *  click on the same node does not re-fetch it. */
  readonly expanded: ReadonlySet<string>
}

export const emptyGraph: GraphView = {
  nodes: [],
  links: [],
  expanded: new Set(),
}

const linkKey = (link: GraphLink): string =>
  `${link.source}|${link.target}|${link.relationshipType}`

/** Merge an arriving neighbourhood into the displayed graph.
 *
 * Node identity is preserved on purpose: `react-force-graph-2d` runs a
 * d3-force simulation that mutates node objects in place to record their
 * `x`/`y` position. Returning a fresh object for a node already on screen
 * would throw that position away, and the whole graph would re-simulate
 * from scratch on every click. So an id already present keeps its existing
 * object reference; only genuinely new ids get new objects.
 *
 * Links are directed and keyed on `source|target|relationshipType` rather
 * than on the unordered pair, because `advised(a→b)` and `advised(b→a)` are
 * different edges and both must survive. What collapses is the same
 * directed edge arriving twice, which happens whenever a neighbourhood is
 * fetched from either of its two endpoints.
 *
 * The root is merged alongside `hood.entities` because the route does not put
 * it there (see `Neighborhood`). Leaving it out is not a missing dot: every
 * relationship in the response has the root at one end, so d3-force resolves
 * those endpoints against a node set the root is absent from and throws
 * `node not found: <root id>`, which takes the canvas down rather than
 * dropping an edge. Every arriving link is anchored at both ends by
 * construction -- the route only returns edges whose two ends are both in the
 * response -- so merging the root is what keeps that invariant true here.
 */
export const expand = (view: GraphView, hood: Neighborhood): GraphView => {
  const existingById = new Map(view.nodes.map((node) => [node.id, node]))
  // Deduplicated on the way in rather than trusted: the root is documented as
  // absent from `entities`, but a response that repeated it would otherwise
  // put the same id in `nodes` twice, and a doubled node draws twice and
  // simulates against itself.
  const arriving = new Map([hood.root, ...hood.entities].map((entity) => [entity.id, entity]))
  const newNodes = Array.from(arriving.values()).filter((node) => !existingById.has(node.id))

  const existingLinkKeys = new Set(view.links.map(linkKey))
  const newLinks = hood.relationships.filter((link) => !existingLinkKeys.has(linkKey(link)))

  return {
    nodes: [...view.nodes, ...newNodes],
    links: [...view.links, ...newLinks],
    expanded: new Set(view.expanded).add(hood.root.id),
  }
}

export const isExpanded = (view: GraphView, id: string): boolean => view.expanded.has(id)
