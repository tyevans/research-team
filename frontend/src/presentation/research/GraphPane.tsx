import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'

import { createGraphStore } from '@application/research/graph-store.ts'
import { useContainer } from '@app/container-context.tsx'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { EmptyState, Loading } from '../common/primitives.tsx'

// `React.lazy`, not a static import: `GraphCanvas` is the only module that
// imports `react-force-graph-2d`, and loading it eagerly would mean every
// page of this console -- a session transcript included -- pays for a
// canvas/d3-force bundle it never draws.
const GraphCanvas = lazy(() =>
  import('./GraphCanvas.tsx').then((module) => ({ default: module.GraphCanvas })),
)

/** The project's knowledge graph, browsed rather than dumped: a search box
 *  finds an entry point, and clicking a node pulls in what lies within one
 *  hop of it.
 *
 * Builds its own store, keyed to this project, the same reason
 * `ExtractionPane` does -- the graph is tenant-scoped, and a store shared
 * across projects would carry one project's nodes onto another's page.
 */
// A full-tenant fetch per call (see `find_entities`'s own docstring) makes
// firing on every keystroke expensive well before the corpus is large --
// this is how many keystrokes of silence the pane waits for before asking.
const SEARCH_DEBOUNCE_MS = 300

export const GraphPane = ({ projectId }: { projectId: ProjectId }) => {
  const { graphs } = useContainer()
  const [term, setTerm] = useState('')
  const [entityType, setEntityType] = useState('')

  const store = useMemo(() => createGraphStore({ graphs, projectId }), [graphs, projectId])
  // Data only, not the methods: `store()` is a hook and can only be called
  // during render, so a handler reaches the actions through `store.getState()`
  // instead (the same split `ExtractionPane` uses). Destructuring them here
  // would also detach them from the store instance the way an unbound method
  // detaches from `this`, which this project's lint config catches.
  const { view, results, truncated, searching, error } = store()

  // Debounced rather than firing on every keystroke: `find_entities` fetches
  // the tenant's entire entity set per call (there is no store-side filter
  // for a substring), so a search box with no debounce would be a full scan
  // per character typed.
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => {
    debounceTimer.current = setTimeout(() => {
      void store.getState().search(term, entityType || undefined)
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(debounceTimer.current)
    // `store` is a stable zustand instance for this pane's lifetime;
    // including it in the deps below would re-run the effect on every
    // render for no reason.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [term, entityType])

  return (
    <div className="graph-browser">
      <div className="graph-controls">
        <input
          type="search"
          role="searchbox"
          className="graph-search"
          placeholder="Search the graph"
          aria-label="Search the graph"
          value={term}
          onChange={(event) => setTerm(event.target.value)}
        />
        <select
          className="graph-entity-type"
          aria-label="Filter by entity type"
          value={entityType}
          onChange={(event) => setEntityType(event.target.value)}
        >
          <option value="">All types</option>
          {Array.from(new Set(results.map((result) => result.entityType)))
            .sort()
            .map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
        </select>
      </div>

      {error ? <p className="graph-error">{error}</p> : null}

      {searching ? <Loading what="entities" /> : null}

      {results.length > 0 ? (
        <>
          {truncated ? (
            <p className="graph-truncated">
              Showing the first {results.length} matches -- narrow the search to see more.
            </p>
          ) : null}
          <ul className="graph-results">
            {results.map((result) => (
              <li key={result.id}>
                <button
                  type="button"
                  className="graph-result"
                  onClick={() => void store.getState().expandNode(result.id)}
                >
                  {result.name}
                  <span className="graph-result-type">{result.entityType}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {view.nodes.length === 0 ? (
        <EmptyState
          title="Nothing expanded yet"
          detail="Search for an entity above and click a result to draw its neighbourhood."
        />
      ) : (
        <Suspense fallback={<Loading what="the graph canvas" />}>
          <GraphCanvas view={view} onNodeClick={(id) => void store.getState().expandNode(id)} />
        </Suspense>
      )}
    </div>
  )
}
