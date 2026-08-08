import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'

import { createGraphStore } from '@application/research/graph-store.ts'
import { useContainer } from '@app/container-context.tsx'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { EmptyState, Loading } from '../common/primitives.tsx'
import { GraphDetail } from './GraphDetail.tsx'
import { GraphLegend } from './GraphLegend.tsx'

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

export const GraphPane = ({
  projectId,
  entity,
  onEntity,
}: {
  projectId: ProjectId
  /** The selected entity, and how to change it. Owned by the route: this pane
   *  asks for a new selection and then reacts to the one that comes back,
   *  rather than keeping its own copy alongside the URL's. Two copies of one
   *  fact is two places for the address bar and the drawing to disagree. */
  entity: string | null
  onEntity: (id: string | null) => void
}) => {
  const { graphs } = useContainer()
  const [term, setTerm] = useState('')
  const [entityType, setEntityType] = useState('')

  const store = useMemo(() => createGraphStore({ graphs, projectId }), [graphs, projectId])
  // Data only, not the methods: `store()` is a hook and can only be called
  // during render, so a handler reaches the actions through `store.getState()`
  // instead (the same split `ExtractionPane` uses). Destructuring them here
  // would also detach them from the store instance the way an unbound method
  // detaches from `this`, which this project's lint config catches.
  const { view, results, knownTypes, truncated, searching, error } = store()

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

  /** The route drives the drawing, not the click.
   *
   * Every selection in this pane goes out through `onEntity`, changes the
   * hash, and arrives back here -- so a node clicked on the canvas and an
   * entity pasted into the address bar take exactly the same path, and the
   * page that loads with `/entity/<id>` in its URL draws that neighbourhood
   * without any separate seeding code. `expandNode` is idempotent (it guards
   * on `isExpanded`) so re-selecting something already drawn costs no request.
   */
  useEffect(() => {
    if (entity === null) {
      store.getState().select(null)
      return
    }
    void store.getState().expandNode(entity)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entity])

  /** Draw what was picked, and get the list out of the way.
   *
   * The results panel floats over the canvas, so leaving it up after a pick
   * covers the very drawing the pick just produced -- you chose a thing in
   * order to look at it, and then had to clear the search box by hand before
   * you could. Clearing the term is what closes the panel, and it also leaves
   * the box empty and ready for the next search, which is the state somebody
   * who has finished with this one wants it in. */
  const pick = (id: string) => {
    setTerm('')
    onEntity(id)
  }

  return (
    <div className="graph-browser">
      {/* The canvas is the layer, and the controls sit on top of it rather
          than in a column above it. Stacked, every search pushed the drawing
          down and a long result list pushed it off screen entirely -- the one
          element that wants the whole box was the one that kept losing it. */}
      <div className="graph-stage">
        {view.nodes.length === 0 ? (
          <EmptyState
            title="Nothing drawn yet"
            detail="Search for an entity and pick a result to draw what connects to it."
          />
        ) : (
          <Suspense fallback={<Loading what="the graph canvas" />}>
            <GraphCanvas view={view} selected={entity} onNodeClick={onEntity} />
          </Suspense>
        )}
        <GraphLegend view={view} />
      </div>

      <div className="graph-command">
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
            {knownTypes.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
          {/* Only once there is something to clear -- a control that does
              nothing is a control a reader has to work out the meaning of. */}
          {view.nodes.length > 0 ? (
            <button
              type="button"
              className="btn btn-sm graph-clear"
              onClick={() => {
                store.getState().clear()
                // The canvas is empty now, so the URL must stop naming a node
                // on it -- otherwise a reload would redraw the thing that was
                // just cleared.
                onEntity(null)
              }}
            >
              Clear
            </button>
          ) : null}
        </div>

        {error ? <p className="graph-error">{error}</p> : null}

        {searching ? (
          <div className="graph-searching">
            <Loading what="entities" />
          </div>
        ) : null}

        {/* Silence read as "still working". A search that matched nothing
            rendered nothing at all, which is exactly what a search still being
            typed renders -- so the one case where the answer was already known
            was the case that looked most like waiting. Only once a term or a
            type has actually been asked for: an empty box has nothing to
            report. */}
        {!searching && !error && (term.trim() || entityType) && results.length === 0 ? (
          <p className="graph-no-results">
            Nothing matched. Try a shorter term, or widen the type filter.
          </p>
        ) : null}

        {results.length > 0 ? (
          <div className="graph-results-panel">
            {truncated ? (
              <p className="graph-truncated">
                First {results.length} matches -- narrow the search to see more.
              </p>
            ) : null}
            <ul className="graph-results" aria-label="Search results">
              {results.map((result) => (
                <li key={result.id}>
                  <button type="button" className="graph-result" onClick={() => pick(result.id)}>
                    <span className="graph-result-name">{result.name}</span>
                    <span className="graph-result-type">{result.entityType}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      {entity ? (
        <GraphDetail
          view={view}
          selected={entity}
          onSelect={onEntity}
          onRemove={(id) => {
            store.getState().removeNode(id)
            onEntity(null)
          }}
          onClose={() => onEntity(null)}
        />
      ) : null}
    </div>
  )
}
