import { create } from 'zustand'

import { errorMessage } from '@application/ports/errors.ts'
import {
  emptyGraph,
  expand,
  isExpanded,
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
  /** Whether the last search matched more entities than the page returned
   *  -- the route paginates but this browser does not, and this is what
   *  keeps that truncation from being silent. */
  readonly truncated: boolean
  readonly searching: boolean
  readonly error: string | null
  search(term: string, entityType?: string): Promise<void>
  expandNode(id: string): Promise<void>
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
    truncated: false,
    searching: false,
    error: null,

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
        set({ results: entities, truncated, searching: false })
      } catch (err) {
        set({ searching: false, error: errorMessage(err) })
      }
    },

    async expandNode(id) {
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
