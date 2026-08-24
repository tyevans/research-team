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
  /** Whether this node was synthesised by a derivation pass rather than
   *  extracted from a document -- today, a discovered ontology class.
   *
   * Load-bearing beyond display, unlike `GraphLink.inferred`: a synthesised
   * node's id comes from the ontology table and belongs to no stored entity,
   * so `/neighborhood` answers 404 for it and `/definition` has nothing to
   * define. `expandNode` reads this to decide whether to fetch at all.
   * Optional for the same reason `temporal` is -- every existing test and
   * construction site predates it. */
  readonly inferred?: boolean
  /** The entity's date or date range, already formatted for display, or
   *  `null` when it has none. Optional because every existing test and
   *  construction site predates this field. */
  readonly temporal?: string | null
}

export interface GraphLink {
  readonly source: string
  readonly target: string
  readonly relationshipType: string
  /** Whether this edge was computed from two entities' dates rather than
   *  asserted by a document -- see `linkKey` for why it is part of identity,
   *  not just a display flag. Optional for the same reason as `temporal`. */
  readonly inferred?: boolean
  /** The arithmetic that produced an inferred edge (e.g. which two extents
   *  overlapped), or `null` for an asserted edge or one predating this field. */
  readonly derivation?: string | null
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

/** A whole project graph as `/api/projects/{id}/graph` returns it: every
 *  entity up to the server's cap, every edge among them, and whether the cap
 *  cut anything off.
 *
 * Flat, with no root, unlike `Neighborhood` -- nobody asked about a
 * particular entity here, which is the entire point of the read.
 */
export interface WholeGraph {
  readonly entities: readonly GraphNode[]
  readonly relationships: readonly GraphLink[]
  readonly truncated: boolean
  /** Whether the inferred edges among `relationships` were themselves capped
   *  (`MAX_INFERRED_EDGES`), independent of `truncated`'s node cap. Required,
   *  unlike the optional fields above: everything that builds a `WholeGraph`
   *  is a mapper or a test fixture, both of which can say `false` outright,
   *  so there is no legacy construction site this has to stay lenient for. */
  readonly inferredTruncated: boolean
}

export interface GraphView {
  readonly nodes: readonly GraphNode[]
  readonly links: readonly GraphLink[]
  /** Node ids whose neighbourhood has already been fetched, so a second
   *  click on the same node does not re-fetch it. */
  readonly expanded: ReadonlySet<string>
}

/** One passage where an entity is mentioned, as the usages route returns it:
 *  which source it came from, the offsets bounding the mention within that
 *  source's text, the mention itself, and the search score that ranked it.
 *
 * `sourceId` is a plain string rather than the branded `SourceId` -- this type
 * mirrors the DTO the way `GraphNode.id` mirrors `entity_id`, and every other
 * id on this page (`GraphNode.id`, `GraphLink.source`/`target`) is unbranded
 * for the same reason: the graph is read from a route that answers in raw
 * UUID strings, and branding here would need a cast the domain gains nothing
 * from. */
export interface Usage {
  readonly sourceId: string
  readonly start: number
  readonly end: number
  readonly text: string
  readonly score: number
}

/** One span a definition drew on. `sourceId`/`start`/`end` rather than the
 *  ask page's `Citation` (`kind`/`id`): that shape names a whole document,
 *  and a definition cites the specific passage within one -- the offsets are
 *  the part worth keeping, not just which source it came from. */
export interface DefinitionCitation {
  readonly sourceId: string
  readonly start: number
  readonly end: number
  /** The moment inside the source this passage sits at, or `null` when the
   *  source has no locator map (every text source, today) or the span
   *  resolved to no `TimeSpan` -- see `presenters.py`'s `definition_view`.
   *  `null` means absent, never zero: `0` is a real citation at the source's
   *  first second, and a check that treats it as falsy drops it silently. */
  readonly atSeconds: number | null
}

/** An entity's generated definition, as the definition route returns it.
 *
 * `text` is nullable: the route answers 200 with `text: null` for an entity
 * the corpus has nothing to ground a definition in, which is a fact about
 * the corpus and not a failure to be retried -- see `presenters.py`'s own
 * docstring on why that is not a 404. `model` and `generatedAt` are `null`
 * together with `text`, for the same reason: there is no generation run to
 * report on.
 *
 * `stale` is server-computed (the text predates the entity's current facts)
 * and is served anyway rather than withheld -- the server's own tradeoff is
 * that older grounded text beats no text while a refresh is in flight. What
 * the panel does with a stale definition is client-side, though: this type
 * only carries the flag the panel reads. */
export interface Definition {
  readonly text: string | null
  readonly citations: readonly DefinitionCitation[]
  readonly model: string | null
  readonly generatedAt: string | null
  readonly stale: boolean
}

export const emptyGraph: GraphView = {
  nodes: [],
  links: [],
  expanded: new Set(),
}

const linkKey = (link: GraphLink): string =>
  // Normalised to a boolean rather than trusting the field's optionality:
  // `undefined` and `false` must key identically, or a link merged twice --
  // once from a source that omitted the field, once from one that set it
  // false -- would duplicate itself.
  `${link.source}|${link.target}|${link.relationshipType}|${link.inferred === true}`

/** Merge an arriving neighbourhood into the displayed graph.
 *
 * Node identity is preserved on purpose: `react-force-graph-2d` runs a
 * d3-force simulation that mutates node objects in place to record their
 * `x`/`y` position. Returning a fresh object for a node already on screen
 * would throw that position away, and the whole graph would re-simulate
 * from scratch on every click. So an id already present keeps its existing
 * object reference; only genuinely new ids get new objects.
 *
 * Links are directed and keyed on `source|target|relationshipType|inferred`
 * rather than on the unordered pair, because `advised(a→b)` and `advised(b→a)`
 * are different edges and both must survive. `inferred` extends that same
 * argument by one field: an asserted `contains` and an inferred `CONTAINS`
 * between the same pair are different claims -- one is what a document said,
 * the other is arithmetic over two dates that changes on re-extraction -- so
 * a key that ignored `inferred` would let one silently displace the other,
 * with which one survived decided by arrival order. What collapses is the
 * same directed edge, with the same provenance, arriving twice -- which
 * happens whenever a neighbourhood is fetched from either of its two
 * endpoints.
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

/** The whole graph, as the view a reader starts from.
 *
 * Replaces rather than merges, which is the opposite of `expand`. A whole
 * graph is not one more piece of the picture; it *is* the picture, and
 * folding it into whatever was already drawn would keep exactly the nodes
 * the server has since dropped -- an entity removed by a merge on the write
 * side would survive on the canvas forever because it once arrived in a
 * neighbourhood. Existing node objects are still reused by id for the ids
 * that survive, for the reason `expand` gives: d3-force stores each node's
 * position on the object, and handing back fresh objects would re-simulate
 * the whole drawing from scratch.
 *
 * **Why the whole graph counts as expanded.** `expanded` means "this node's
 * neighbours are already on screen", which for a complete graph is true of
 * every node in it -- so clicking one draws its detail panel without
 * spending a request re-fetching edges already drawn, and the canvas's
 * hollow-means-more-behind ring correctly shows nothing left to find. That
 * claim fails the moment the cap bites: a truncated graph is missing both
 * entities and the edges that reached them, so no node can be promised its
 * neighbours are all here, and every one stays clickable for real.
 */
export const loadWhole = (view: GraphView, graph: WholeGraph): GraphView => {
  const existingById = new Map(view.nodes.map((node) => [node.id, node]))
  const nodes = graph.entities.map((entity) => existingById.get(entity.id) ?? entity)

  return {
    nodes,
    links: graph.relationships,
    expanded: graph.truncated ? new Set() : new Set(nodes.map((node) => node.id)),
  }
}

export const isExpanded = (view: GraphView, id: string): boolean => view.expanded.has(id)

/** One end of a link, as an id, whichever form it is currently in.
 *
 * `GraphLink` declares `source` and `target` as ids, and they are ids right up
 * until the drawing gets hold of them: d3-force replaces each one with a
 * reference to the node object it resolved to, in place, on the very objects
 * this module handed it. So a link read back after the canvas has drawn it
 * once has node objects where a caller would reasonably expect strings, and
 * code that assumes either form alone is right exactly half the time.
 */
const endpointId = (endpoint: unknown): string =>
  typeof endpoint === 'string'
    ? endpoint
    : String((endpoint as { id?: unknown } | null)?.id ?? endpoint)

/** Take one entity off the drawing, and anything left stranded by its going.
 *
 * Browsing accumulates. Ten expansions in, the interesting part is buried in
 * everything that came along on the way, and the only way back was to reload
 * the page and start over -- which threw away the nine expansions worth
 * keeping along with the one that was not.
 *
 * **What else goes.** Removing an entity strands its neighbours: nodes that
 * arrived only because they were connected to this one, and that now sit on
 * the canvas connected to nothing. Those go too. Nodes the reader *chose* --
 * anything they expanded themselves -- stay, even when removing this one
 * leaves them unconnected, because a thing you asked for should not vanish as
 * a side effect of tidying up something else. That is the whole rule: the
 * graph keeps what you asked for and drops what merely came with it.
 *
 * The removed id also leaves `expanded`, so it can be drawn again later. A
 * node you took off the canvas and then searched out again should arrive with
 * its neighbourhood, not as a bare dot whose expansion the store thinks it has
 * already done.
 */
export const remove = (view: GraphView, id: string): GraphView => {
  const links = view.links.filter(
    (link) => endpointId(link.source) !== id && endpointId(link.target) !== id,
  )

  const stillLinked = new Set(
    links.flatMap((link) => [endpointId(link.source), endpointId(link.target)]),
  )

  const nodes = view.nodes.filter(
    (node) => node.id !== id && (stillLinked.has(node.id) || view.expanded.has(node.id)),
  )

  const kept = new Set(nodes.map((node) => node.id))
  const expanded = new Set([...view.expanded].filter((expandedId) => kept.has(expandedId)))

  return { nodes, links, expanded }
}

/** A link seen from one of its ends: which way it points, and what is at the
 *  other end. */
export interface GraphEdgeView {
  readonly relationshipType: string
  /** `out` when the selected node is this link's source. */
  readonly direction: 'out' | 'in'
  readonly other: GraphNode
}

/** Every link touching `id`, resolved to the node at the other end.
 *
 * Direction is kept rather than flattened to "connected to": `advised(a→b)`
 * and `advised(b→a)` say different things, and a list that showed both as the
 * same row would be describing a different graph from the one on screen.
 */
export const edgesOf = (view: GraphView, id: string): readonly GraphEdgeView[] => {
  const byId = new Map(view.nodes.map((node) => [node.id, node]))

  return view.links.flatMap((link) => {
    const source = endpointId(link.source)
    const target = endpointId(link.target)
    const otherId = source === id ? target : target === id ? source : null
    if (otherId === null) return []

    const other = byId.get(otherId)
    // A link whose far end is not in the node set cannot be drawn as a row
    // any more than it can be drawn as a line. `expand` maintains that this
    // does not happen; this is the reading side of the same invariant.
    if (!other) return []

    const edge: GraphEdgeView = {
      relationshipType: link.relationshipType,
      direction: source === id ? 'out' : 'in',
      other,
    }
    return [edge]
  })
}

/** How many links touch each node, keyed by id, with a zero for the nodes
 *  nothing touches.
 *
 * The zeroes are the point: the callers of this count nodes *below* a
 * threshold, so a map that simply omitted the unconnected ones would answer
 * `undefined` for exactly the case being asked about.
 *
 * A link counts once for each end it has here, so a self-loop scores two on
 * its one node. Nothing in this graph writes self-loops today, and defining
 * them away would be a rule maintained against no case.
 */
export const degrees = (view: GraphView): ReadonlyMap<string, number> => {
  const counts = new Map(view.nodes.map((node) => [node.id, 0]))
  for (const link of view.links) {
    const source = endpointId(link.source)
    const target = endpointId(link.target)
    // Both ends have to be drawn, not just the one being counted. A link
    // reaching out of the view is not a connection the reader can see, and
    // scoring its near end for it would keep a visibly unconnected dot on a
    // canvas filtered to hide exactly those.
    if (!counts.has(source) || !counts.has(target)) continue
    counts.set(source, (counts.get(source) ?? 0) + 1)
    counts.set(target, (counts.get(target) ?? 0) + 1)
  }
  return counts
}

/** The drawing with every node of fewer than `min` connections taken off it,
 *  and every link left dangling by their going.
 *
 * Filtering rather than removal (`remove`, above) is the distinction worth
 * holding on to: `remove` is a reader's edit to the graph they are browsing
 * and takes stranded neighbours with it, while this is a lens over whatever
 * the graph currently is. It keeps `expanded` whole, so lifting the threshold
 * back down redraws exactly what was there and costs no request.
 *
 * Degrees are counted once, against the graph as it arrived, and the filter is
 * a single pass -- so at `min` of 2 a kept node may end up drawn with one line,
 * because the node at the other end of its second link fell below the
 * threshold itself. The alternative is iterating to a fixed point, which reads
 * as "nodes in a subgraph where everything has N connections" rather than
 * "nodes with N connections", and at a threshold of 3 or more it collapses
 * most real graphs to nothing in a way no reader would predict from the
 * control they turned.
 *
 * `min <= 0` returns the view unchanged, by identity -- the canvas memoises on
 * `view`, so a filter that rebuilt an equal object at the default threshold
 * would reheat the simulation on every render.
 */
export const withMinDegree = (
  view: GraphView,
  min: number,
  /** Ids the threshold does not apply to -- today, whatever the reader has
   *  selected. A node chosen by name out of the search results has to be drawn
   *  whatever its degree: the alternative is that picking an entity nothing was
   *  ever related to blanks the stage and the panel describes something the
   *  canvas does not show. This is `remove`'s rule in another form -- the graph
   *  keeps what you asked for. */
  keep: ReadonlySet<string> = new Set(),
): GraphView => {
  if (min <= 0) return view

  const counts = degrees(view)
  const nodes = view.nodes.filter((node) => keep.has(node.id) || (counts.get(node.id) ?? 0) >= min)
  const kept = new Set(nodes.map((node) => node.id))
  const links = view.links.filter(
    (link) => kept.has(endpointId(link.source)) && kept.has(endpointId(link.target)),
  )

  return { nodes, links, expanded: view.expanded }
}
