import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'

import { createGraphStore } from '@application/research/graph-store.ts'
import { useContainer } from '@app/container-context.tsx'
import { useInteractionLog } from '@app/interaction-log-provider.tsx'
import type { GraphNode, GraphView } from '@domain/knowledge/graph.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { EmptyState, Loading } from '../common/primitives.tsx'
import { useFrameRefresh } from '../shell/use-frame-refresh.ts'
import { GraphDetail } from './GraphDetail.tsx'
import { GraphExportBar } from './GraphExportBar.tsx'
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

/** The stage's faint graph-paper field, so an empty stage reads as somewhere a
 *  graph goes rather than as a panel that failed to load, and a sparse graph
 *  has something to sit against.
 *
 * **An inline style rather than a utility, and the reason is legibility rather
 * than impossibility.** `bg-[image:…]` would take it: two `linear-gradient`s at
 * a `color-mix` of the token line colour, with every space written as an
 * underscore and the pair separated by a comma inside the same bracket. That
 * string is unreadable, and — unlike the spacing families — `check-tailwind.mjs`
 * does not cover `bg-`, so a typo in it emits no rule, no warning and no visual
 * tell on a stage that is *supposed* to be nearly blank. An inline style is the
 * same declarations in the spelling CSS uses, and it carries no `z-index`, so
 * it is outside what `scripts/stacking.test.ts` exists to stop.
 *
 * Module-level so it is one object rather than one per render; the drawing
 * above it reheats on identity changes and this sits under the same subtree. */
const STAGE_FIELD = {
  backgroundImage: [
    'linear-gradient(color-mix(in srgb, var(--line-soft) 55%, transparent) 1px, transparent 1px)',
    'linear-gradient(90deg, color-mix(in srgb, var(--line-soft) 55%, transparent) 1px, transparent 1px)',
  ].join(', '),
  backgroundSize: '40px 40px',
  backgroundPosition: 'center',
} as const

/** The floating command bar's panels, which are three different elements
 *  saying the same thing: a bordered, raised card lifted off the canvas — the
 *  only thing on this page that can scroll underneath a control. */
const PANEL = 'rounded-md border border-solid border-line bg-bg-panel shadow-1'

/** A search result: a full-width bare button, the same row vocabulary
 *  `GraphDetail`'s edges use, and inward-ringed for the same measured reason —
 *  the results panel's padding is 4px against a ring that reaches 3px outward,
 *  which is slack rather than clearance. See `ROW` in `GraphDetail.tsx`; the
 *  two are deliberately not shared, because these rows are a baseline-aligned
 *  name/type pair and those are a stacked two-line label, and folding them into
 *  one constant with a variant flag would be an abstraction over a coincidence. */
const RESULT_ROW = [
  'flex w-full cursor-pointer items-baseline justify-between gap-2',
  'border-0 border-l-2 border-solid border-l-transparent rounded-md',
  'bg-transparent px-[8px] py-[5px] text-left text-sm text-inherit [font:inherit]',
  'hover:bg-bg-hover hover:border-l-accent',
  'focus-visible:bg-bg-hover focus-visible:border-l-accent',
  'lay-ring-inward',
].join(' ')

/** The two capped-graph notices and the "first N matches" line, all three of
 *  which were `.graph-truncated`.
 *
 * The bottom rule is kept on all three even though only the one inside the
 * results panel has anything below it to be separated from — that is what the
 * class did, and this rewrite is rule-for-rule rather than a redesign. The two
 * that float bare over the canvas therefore still draw a hairline under
 * themselves with no panel behind it; it is odd, it was odd before, and
 * changing it here would hide a design question inside a migration. */
const NOTICE =
  'm-0 border-0 border-b border-solid border-b-line-soft px-[6px] pb-[6px] pt-[4px] text-xs text-fg-dim'

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
  const { graphs, exports } = useContainer()
  const [term, setTerm] = useState('')
  const [entityType, setEntityType] = useState('')

  const log = useInteractionLog()
  const store = useMemo(
    () => createGraphStore({ graphs, projectId, emitter: log }),
    [graphs, projectId, log],
  )
  // Data only, not the methods: `store()` is a hook and can only be called
  // during render, so a handler reaches the actions through `store.getState()`
  // instead (the same split `ExtractionPane` uses). Destructuring them here
  // would also detach them from the store instance the way an unbound method
  // detaches from `this`, which this project's lint config catches.
  const { view, results, knownTypes, truncated, searching, error, partial, edgesPartial, loading } =
    store()

  /** Draw the whole graph before the reader asks for anything.
   *
   * The pane used to open on an empty canvas and stay there until somebody
   * searched, which put the burden the wrong way round: knowing an entity's
   * name is the *result* of reading a project's graph, not the price of
   * admission to it. Worse, the blank canvas said the same thing whether the
   * project had nine hundred entities or none.
   *
   * Once per project, not per render: `store` is rebuilt when `projectId`
   * changes and this rides along with it.
   */
  useEffect(() => {
    void store.getState().loadAll()
  }, [store])

  /** Draw what has been extracted since, without waiting to be reloaded.
   *
   * The effect above runs once per project, so before this the drawing was
   * the graph as it stood when the tab opened -- a reader could watch a
   * transcript report twelve entities against a canvas showing none of them,
   * and the only way through was F5.
   *
   * `loadAll` rather than a merge of something on the frame: the frame
   * carries no entities on purpose (`graph_change` says why), and the route
   * stays the single answer to what the graph is. The cost is real and worth
   * stating -- `loadWhole` replaces the drawing, so a reader who has pruned
   * nodes gets them back. That is the same trade "Reset view" makes
   * deliberately, made here by an extraction they did not ask for. Their
   * *selection* survives (`loadAll` keeps it when the node is still in the
   * graph), which is the part the detail panel depends on. A merge that kept
   * pruning would have to decide what a removed node means once the server
   * has merged it into one that is still there, and that is not a question
   * this pane can answer correctly today.
   *
   * Corpus frames are ignored: they ride the same ingest, and a document
   * being stored changes no entity. Asserted, along with the project scoping.
   */
  useFrameRefresh(
    // Always on: this hook lives in the pane it refreshes, so being mounted
    // is the "on screen" test `useTreeRefresh` needs its flag for.
    true,
    (frame) => frame.kind === 'graph' && frame.projectId === projectId,
    () => void store.getState().loadAll(),
  )

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
    <GraphBrowser
      projectId={projectId}
      view={view}
      results={results}
      knownTypes={knownTypes}
      truncated={truncated}
      searching={searching}
      error={error}
      partial={partial}
      edgesPartial={edgesPartial}
      loading={loading}
      entity={entity}
      term={term}
      entityType={entityType}
      onTerm={setTerm}
      onEntityType={setEntityType}
      onEntity={onEntity}
      onPick={pick}
      onReset={() => {
        void store.getState().reset()
        // The selection is dropped with it: whatever was being described was
        // chosen out of the drawing that is now gone, and a reload should open
        // on the whole graph rather than on one node of a view the reader had
        // just abandoned.
        onEntity(null)
      }}
      onRemove={(id) => {
        store.getState().removeNode(id)
        onEntity(null)
      }}
      graphUrl={(format, entityId) =>
        exports.graphUrl(
          projectId,
          format,
          // Depth 1, matching what clicking a node in this pane pulls in. A
          // deeper export would hand back a drawing the reader has not seen,
          // and `MAX_NEIGHBORHOOD_DEPTH` is 2 -- so the only other choice is
          // one the server may refuse.
          entityId === null ? { kind: 'project' } : { kind: 'entity', entityId, depth: 1 },
        )
      }
    />
  )
}

/** The graph, drawn from a view somebody else is keeping current.
 *
 * Everything above this line is subscription: a store per project, a load on
 * mount, a reload on every graph frame, a debounced search. Everything below
 * is what those produce on screen. The split is worth the prop list because
 * the states this pane can be in are numerous and each one used to need a fake
 * repository to reach -- empty because nothing is extracted, empty because the
 * fetch failed (which must *not* say the graph is empty), capped, searching,
 * searched-and-matched-nothing, and a result list over a drawing.
 *
 * Named `GraphBrowser` after the element it owns: the stage, the floats on it,
 * and nothing above them.
 */
export const GraphBrowser = ({
  projectId,
  view,
  results,
  knownTypes,
  truncated,
  searching,
  error,
  partial,
  edgesPartial,
  loading,
  entity,
  term,
  entityType,
  onTerm,
  onEntityType,
  onEntity,
  onPick,
  onReset,
  onRemove,
  graphUrl,
}: {
  projectId: ProjectId
  view: GraphView
  results: readonly GraphNode[]
  knownTypes: readonly string[]
  /** The result list was cut short by the server. */
  truncated: boolean
  searching: boolean
  /** Why the last fetch failed, if it did. Distinct from an empty graph, and
   *  the reason the empty state below reads its own message off it. */
  error: string | null
  /** The drawing is part of a larger graph. */
  partial: boolean
  /** The temporal edges among the drawn nodes were themselves capped, which
   *  `partial` does not cover: a graph under the node cap can still have more
   *  inferred lines than were computed for it. */
  edgesPartial: boolean
  loading: boolean
  entity: string | null
  term: string
  entityType: string
  onTerm: (value: string) => void
  onEntityType: (value: string) => void
  onEntity: (id: string | null) => void
  /** A result was chosen: select it *and* close the list over the canvas. */
  onPick: (id: string) => void
  onReset: () => void
  onRemove: (id: string) => void
  /** Where a file of this graph can be downloaded, narrowed to `entity` when
   *  one is selected. A prop rather than a container read inside the export
   *  bar, so this component keeps taking everything it needs from its caller —
   *  which is what lets the browser-mode test render it against a partial
   *  container. */
  graphUrl: (format: 'html' | 'json' | 'graphml', entityId: string | null) => string
}) => {
  return (
    // `relative` is load-bearing rather than decorative: it is the containing
    // block every float below positions against, and `GraphCanvas`'s
    // `absolute inset-0` resolves to it too.
    <div className="relative flex min-h-0 flex-1">
      {/* The canvas is the layer, and the controls sit on top of it rather
          than in a column above it. Stacked, every search pushed the drawing
          down and a long result list pushed it off screen entirely -- the one
          element that wants the whole box was the one that kept losing it.

          Deliberately *not* `relative`: the canvas positions against the
          browser box rather than this one, so it fills the whole stage rather
          than being confined to whatever the centred flex line is tall. */}
      <div className="flex min-h-0 flex-1 items-center justify-center" style={STAGE_FIELD}>
        {loading && view.nodes.length === 0 ? (
          <Loading what="the knowledge graph" />
        ) : view.nodes.length === 0 ? (
          // Nothing drawn now means nothing extracted, not "you have not
          // searched yet" -- the pane has already asked for everything.
          // Unless the ask failed, in which case the error below the canvas
          // is the answer and this must not claim the graph is empty.
          <EmptyState
            heading={error ? 'The graph could not be read' : 'This graph is empty'}
            detail={
              error
                ? 'The project may still have entities; this page could not fetch them.'
                : 'Nothing has been extracted into this project yet. Ingest a document to start building it.'
            }
          />
        ) : (
          <Suspense fallback={<Loading what="the graph canvas" />}>
            <GraphCanvas view={view} selected={entity} onNodeClick={onEntity} />
          </Suspense>
        )}
        <GraphLegend view={view} />
      </div>

      {/* Bounded rather than stretched: a bar running the full width of the
          stage would read as a header and cover the drawing it is meant to sit
          on. */}
      <div className="lay-region-float absolute top-3 left-3 flex w-[min(320px,calc(100%_-_20px))] flex-col gap-2">
        <div className={`flex gap-2 p-2 ${PANEL}`}>
          <input
            type="search"
            role="searchbox"
            className="input min-w-0 flex-1"
            placeholder="Search the graph"
            aria-label="Search the graph"
            value={term}
            onChange={(event) => onTerm(event.target.value)}
          />
          {/* `maxWidth` inline, and it has to be. The rule this replaces was
              `select.graph-entity-type` rather than `.graph-entity-type`
              precisely because the shared field style caps a `<select>` at
              22rem for the workflow menu, and `select.input` outranks a bare
              class. A Tailwind `max-w-[40%]` loses that contest twice over --
              lower specificity *and* `@layer utilities` against an unlayered
              rule -- so the type menu would render wider than the command bar
              it sits in, with `shrink-0` refusing to take it back. An inline
              style is the only spelling that beats an unlayered `select.input`
              without an `!important` this codebase uses nowhere else. It goes
              when `.input` does. */}
          <select
            className="input shrink-0"
            style={{ maxWidth: '40%' }}
            aria-label="Filter by entity type"
            value={entityType}
            onChange={(event) => onEntityType(event.target.value)}
          >
            <option value="">All types</option>
            {knownTypes.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
          {/* "Reset", not "Clear": with the whole graph drawn by default, an
              empty canvas is no longer a state worth offering a button for --
              it is the state a reader would immediately have to undo. What
              they actually want back after pruning and expanding is
              everything, which is what this restores. */}
          {view.nodes.length > 0 ? (
            <button type="button" className="btn btn-sm shrink-0" onClick={onReset}>
              Reset view
            </button>
          ) : null}
        </div>

        {/* Only once there is something to export. An export of an empty graph
            is a valid file nobody wants, and offering it on a stage that says
            "this graph is empty" would contradict the stage. */}
        {view.nodes.length > 0 ? (
          <GraphExportBar
            graphUrl={graphUrl}
            entity={entity}
            entityName={view.nodes.find((node) => node.id === entity)?.name ?? null}
          />
        ) : null}

        {/* Bordered in the failure colour rather than merely coloured text:
            this floats over a drawing, so it needs its own box to be legible
            against whatever the simulation put behind it. */}
        {error ? (
          <p className="m-0 rounded-md border border-solid border-k-failure bg-bg-panel px-[8px] py-[5px] text-xs text-k-failure">
            {error}
          </p>
        ) : null}

        {/* A capped graph draws exactly like a complete one, and is missing
            the edges to what was cut as well as the nodes themselves. Saying
            so is also what points a reader at the search box, which is the
            way through a graph too big to take in whole. */}
        {partial ? (
          <p className={NOTICE}>
            Showing part of a larger graph -- search to find what is not drawn.
          </p>
        ) : null}

        {/* A drawing missing temporal edges looks exactly like a drawing with
            none to miss, and this is the only case that says otherwise: it
            can fire even when `partial` is false, since the edge cap and the
            node cap are independent. */}
        {edgesPartial ? (
          <p className={NOTICE}>Some inferred date relationships are not drawn.</p>
        ) : null}

        {/* A graph with entities and no edges between them draws as a field of
            unconnected dots, which is what a graph whose *edges* failed to load
            would look like too -- and the reader has no way to tell those
            apart. Saying it outright is the only thing that does.

            Not folded into `edgesPartial` above: that one says some edges were
            cut, and this one says there were none to cut. A project with 2,525
            entities and 8 dated ones hits this, and used to hit it silently. */}
        {view.nodes.length > 0 && view.links.length === 0 ? (
          <p className={NOTICE}>No relationships were found between these entities.</p>
        ) : null}

        {searching ? (
          <div className={`px-[8px] py-2 ${PANEL}`}>
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
          // Styled like the results panel it stands in for, because that is
          // what it is: the answer to the same search, in the case where the
          // answer is none.
          <p className={`m-0 px-[8px] py-2 text-xs text-fg-dim ${PANEL}`}>
            Nothing matched. Try a shorter term, or widen the type filter.
          </p>
        ) : null}

        {results.length > 0 ? (
          // The list scrolls inside the floating panel instead of growing
          // down the page, so the number of matches cannot change how much
          // graph you can see.
          <div
            data-result-scroll
            className={`max-h-[min(340px,calc(100vh_-_260px))] overflow-y-auto p-[4px] ${PANEL}`}
          >
            {truncated ? (
              <p className={NOTICE}>
                First {results.length} matches -- narrow the search to see more.
              </p>
            ) : null}
            {/* Rows, not wrapped chips: this is a list you read down looking
                for one name, and chips of varying width made that a scan in two
                dimensions. */}
            <ul className="m-0 flex list-none flex-col gap-[1px] p-0" aria-label="Search results">
              {results.map((result) => (
                <li key={result.id}>
                  <button
                    type="button"
                    data-result-row
                    className={RESULT_ROW}
                    onClick={() => onPick(result.id)}
                  >
                    <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
                      {result.name}
                    </span>
                    <span className="shrink-0 font-mono text-xs text-fg-dim">
                      {result.entityType}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      {entity ? (
        <GraphDetail
          projectId={projectId}
          view={view}
          selected={entity}
          onSelect={onEntity}
          onRemove={onRemove}
          onClose={() => onEntity(null)}
        />
      ) : null}
    </div>
  )
}
