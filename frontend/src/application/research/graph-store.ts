import { create } from 'zustand'

import { errorMessage } from '@application/ports/errors.ts'
import {
  emptyGraph,
  expand,
  isExpanded,
  loadWhole,
  remove,
  type GraphNode,
  type GraphView,
} from '@domain/knowledge/graph.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import type { GraphRepository } from '../ports/repositories.ts'

/** One project's browsable knowledge graph: the current search results, and
 *  the subgraph a reader has expanded so far.
 *
 * Project-keyed for the same reason `extraction-store` is: the graph is
 * tenant-scoped by project, and a store shared across projects would show
 * one project's nodes on another's page the moment two tabs were open.
 */
export interface GraphState {
  readonly view: GraphView
  readonly results: readonly GraphNode[]
  /** Every entity type this store has seen a result for, sorted.
   *
   * Accumulated rather than derived from `results`, because the control that
   * offers these re-queries the server when one is chosen: picking `fact`
   * makes the results all facts, and a list derived from them would drop every
   * other option from the very control that had just offered it. A type seen
   * once stays on offer for the rest of the visit. */
  readonly knownTypes: readonly string[]
  /** Whether the last search matched more entities than the page returned
   *  -- the route paginates but this browser does not, and this is what
   *  keeps that truncation from being silent. */
  readonly truncated: boolean
  readonly searching: boolean
  readonly error: string | null
  /** The node whose connections are on show, or null.
   *
   * Kept here rather than in the pane because expanding sets it: clicking a
   * node is one gesture, and it should both draw what is around that node and
   * say what it is. Two pieces of state for one gesture would be two places
   * for the answer to disagree with the drawing. */
  readonly selected: string | null
  /** Whether the drawing is the whole graph or the first `MAX_GRAPH_NODES` of
   *  a bigger one. The reader has to be told: a capped graph looks exactly
   *  like a complete one, and it is missing edges as well as nodes. */
  readonly partial: boolean
  /** Whether the temporal edges the server computed were themselves capped
   *  (`MAX_INFERRED_EDGES`), independent of `partial`'s node cap. A drawing
   *  missing lines looks exactly like a drawing with none to miss -- this is
   *  what keeps that silent. */
  readonly edgesPartial: boolean
  readonly loading: boolean
  /** Draw the project's whole graph. What the pane opens with, rather than
   *  waiting for a search: a reader arriving at a project they have not read
   *  yet has no entity name to type, and an empty canvas cannot tell them
   *  whether that is because the graph is empty or because they have not
   *  asked it anything. */
  loadAll(): Promise<void>
  search(term: string, entityType?: string): Promise<void>
  expandNode(id: string): Promise<void>
  select(id: string | null): void
  /** Take one entity off the drawing. See `remove` for what goes with it. */
  removeNode(id: string): void
  /** Put back everything pruning and expanding have changed, by drawing the
   *  whole graph again.
   *
   * Re-fetched rather than restored from a copy kept aside: what the server
   * holds moves while the page is open -- extraction runs, entities merge --
   * and a snapshot taken at mount would quietly become the stale answer to
   * "show me everything" the longer the tab stayed open.
   *
   * The search results are left alone. Resetting the drawing is not the same
   * as forgetting what you searched for, and having to retype the term to
   * draw a second thing would be. */
  reset(): Promise<void>
}

export type GraphStore = ReturnType<typeof createGraphStore>

export const createGraphStore = ({
  graphs,
  projectId,
}: {
  graphs: GraphRepository
  projectId: ProjectId
}) =>
  create<GraphState>((set, get) => ({
    view: emptyGraph,
    results: [],
    knownTypes: [],
    truncated: false,
    searching: false,
    error: null,
    selected: null,
    partial: false,
    edgesPartial: false,
    loading: false,

    async loadAll() {
      set({ loading: true, error: null })
      try {
        const graph = await graphs.whole(projectId)
        set((state) => ({
          view: loadWhole(state.view, graph),
          partial: graph.truncated,
          edgesPartial: graph.inferredTruncated,
          loading: false,
          // A selection that survived into the new drawing stays; one that
          // did not would leave the detail panel describing a node the
          // reader can no longer see or click.
          selected:
            state.selected && graph.entities.some((entity) => entity.id === state.selected)
              ? state.selected
              : null,
        }))
      } catch (err) {
        // The canvas keeps whatever it had. On the opening load that is
        // nothing, and the empty state stands with the error beside it --
        // which is the honest reading: the graph is not known to be empty,
        // it is unknown.
        set({ loading: false, error: errorMessage(err) })
      }
    },

    async reset() {
      await get().loadAll()
    },

    select(id) {
      set({ selected: id })
    },

    removeNode(id) {
      set((state) => {
        const view = remove(state.view, id)
        return {
          view,
          // The panel describes the selection, so a selection that is no
          // longer on the canvas would leave it describing something the
          // reader cannot see. This covers the removed node and anything that
          // went with it.
          selected:
            state.selected && view.nodes.some((node) => node.id === state.selected)
              ? state.selected
              : null,
        }
      })
    },

    async search(term, entityType) {
      const needle = term.trim()
      // A blank search with no type filter clears the list rather than
      // asking the server for every entity in the project -- there is no
      // route that lists them all, and a substring match on '' would be
      // exactly that. A type filter alone is still a real query: "every
      // entity of this type" is a legitimate entry point the port already
      // supports.
      if (!needle && !entityType) {
        set({ results: [], truncated: false })
        return
      }
      set({ searching: true, error: null })
      try {
        const { entities, truncated } = await graphs.search(projectId, needle, entityType)
        set((state) => ({
          results: entities,
          truncated,
          searching: false,
          knownTypes: [
            ...new Set([...state.knownTypes, ...entities.map((entity) => entity.entityType)]),
          ].sort(),
        }))
      } catch (err) {
        set({ searching: false, error: errorMessage(err) })
      }
    },

    async expandNode(id) {
      // Selecting happens before the guard below and before the request:
      // clicking an already-expanded node still means "tell me about this
      // one", and a reader who clicks a node whose neighbourhood is already
      // drawn should not be the only one who gets no answer.
      set({ selected: id })

      // The guard `expand`'s own docstring calls out: a second click on a
      // node already on screen must not re-issue the request that put it
      // there.
      if (isExpanded(get().view, id)) return
      set({ error: null })
      try {
        const hood = await graphs.neighborhood(projectId, id)
        set((state) => ({ view: expand(state.view, hood) }))
      } catch (err) {
        // A 422 (too-deep a request) or any other failure surfaces here
        // rather than being swallowed -- the view stays exactly as it was,
        // and the reader is told why nothing changed.
        set({ error: errorMessage(err) })
      }
    },
  }))
