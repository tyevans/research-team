import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { createGraphStore } from '@application/research/graph-store.ts'
import { useContainer } from '@app/container-context.tsx'
import { useInteractionLog } from '@app/interaction-log-provider.tsx'
import { groupByType, type EntityGroup } from '@domain/knowledge/entity-tree.ts'
import type { GraphView } from '@domain/knowledge/graph.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { EmptyState, Loading } from '../common/primitives.tsx'
import { projectHref } from '../routing/routes.ts'
import { useFrameRefresh } from '../shell/use-frame-refresh.ts'
import { EntityTree } from './EntityTree.tsx'
import { GraphDetail } from './GraphDetail.tsx'

/** The two capped/undated notices, matching `GraphPane`'s `NOTICE` rule word
 *  for word -- `border-0` before the directional width is not optional: this
 *  build imports no preflight, so `border-solid` with only `border-b` set
 *  would draw the browser's ~3px default on the other three sides. */
const NOTICE =
  'm-0 border-0 border-b border-solid border-b-line-soft px-[6px] pb-[6px] pt-[4px] text-xs text-fg-dim'

/** Small graphs open; big ones do not.
 *
 * The tab exists to enumerate, and a screen of closed headings enumerates
 * nothing -- but every group open on a nine-hundred-entity graph is the
 * canvas's hairball set in a different font. 200 is **chosen, not measured**:
 * it is roughly the point at which the list stops being one scroll.
 *
 * Applied once per project rather than on every load, and that is the part
 * with a defect behind it: `loadAll` runs again on every `graph` frame, so
 * recomputing here would silently undo a reader's collapses during the one
 * activity that makes this list change.
 */
const OPEN_ALL_BELOW = 200

/** The project's entities under collapsible type headings: an alternative
 *  reading of the material `GraphPane` draws as a canvas.
 *
 * Structurally `TimelinePane`, deliberately: a store per project, a load on
 * mount, a reload on every `graph` frame, and `GraphDetail` reached with
 * `showInGraphHref` and no `onRemove` -- there is no drawing here to prune, so
 * offering Remove would be a button that either does nothing or silently
 * changes another tab.
 */
export const EntityTreePane = ({
  projectId,
  entity,
  onEntity,
}: {
  projectId: ProjectId
  /** The selected entity, and how to change it. Owned by the route, the same
   *  arrangement `GraphPane` and `TimelinePane` use. */
  entity: string | null
  onEntity: (id: string | null) => void
}) => {
  const { graphs } = useContainer()
  const log = useInteractionLog()
  const store = useMemo(
    () => createGraphStore({ graphs, projectId, emitter: log }),
    [graphs, projectId, log],
  )
  const { view, loading, error, partial } = store()

  const [term, setTerm] = useState('')
  const groups = useMemo(() => groupByType(view.nodes, term), [view.nodes, term])

  const [open, setOpen] = useState<ReadonlySet<string>>(new Set())
  // The project the default openness was last computed for. A ref rather
  // than state: recomputing on every `loadAll` (which runs on every `graph`
  // frame) would silently undo a reader's collapses during the one activity
  // that makes this list change, so the default is applied once per project
  // and never again on its own.
  const defaultedFor = useRef<ProjectId | null>(null)

  /** Apply the default openness once a fetch that actually found something has
   *  landed. Checked after *every* `loadAll` -- the mount load and every
   *  `graph`-frame reload alike -- not only the mount load's own promise:
   *  a project mid-extraction has zero nodes at mount, and a project that
   *  only ever checked the mount load would never revisit that decision, so
   *  every group that arrived on a later frame would render closed for the
   *  rest of the session, on a graph of any size -- the exact state
   *  `OPEN_ALL_BELOW` exists to avoid. The ref still guards "once per
   *  project": the first load with a nonzero node count wins and spends the
   *  token, and no load after that touches `open` again, so a reader's
   *  collapses survive every reload that follows. Residual, and acceptable: a
   *  project that stays genuinely empty forever never defaults, which costs
   *  nothing because it renders the empty state regardless. */
  const applyDefaultOpenness = useCallback(
    (forProject: ProjectId) => {
      if (defaultedFor.current === forProject) return
      const nodes = store.getState().view.nodes
      if (nodes.length === 0) return
      defaultedFor.current = forProject
      setOpen(
        nodes.length < OPEN_ALL_BELOW
          ? new Set(groupByType(nodes).map((group) => group.entityType))
          : new Set(),
      )
    },
    [store],
  )

  useEffect(() => {
    void store
      .getState()
      .loadAll()
      .then(() => applyDefaultOpenness(projectId))
  }, [store, projectId, applyDefaultOpenness])

  useFrameRefresh(
    true,
    (frame) => frame.kind === 'graph' && frame.projectId === projectId,
    () =>
      void store
        .getState()
        .loadAll()
        .then(() => applyDefaultOpenness(projectId)),
  )

  const toggle = (entityType: string) => {
    setOpen((current) => {
      const next = new Set(current)
      if (next.has(entityType)) next.delete(entityType)
      else next.add(entityType)
      return next
    })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 px-2 py-1">
        <input
          type="search"
          className="input min-w-0 flex-1"
          placeholder="Filter entities"
          aria-label="Filter entities"
          value={term}
          onChange={(event) => setTerm(event.target.value)}
        />
      </div>

      <EntityTreeBrowser
        projectId={projectId}
        view={view}
        groups={groups}
        open={open}
        selected={entity}
        loading={loading}
        error={error}
        partial={partial}
        filtered={term.trim() !== ''}
        onToggle={toggle}
        onSelect={(id) => {
          // The emitter this pane hands its store was unused: selection goes
          // out through `onEntity` to the route, and nothing here ever called
          // `select` or `expandNode`, so opening an entity from the tree
          // recorded no `EntityOpened` at all. It records one now, under its
          // own source rather than the store's `'graph'` default -- picking a
          // name out of a list and clicking a node on a canvas are different
          // gestures and the field exists to tell them apart.
          store.getState().select(id, 'tree')
          onEntity(id)
        }}
        onClose={() => onEntity(null)}
      />
    </div>
  )
}

/** Everything the pane draws, as a function of what it was given.
 *
 * Split out and exported for the reason `GraphBrowser` is: every state --
 * loading, error, empty (three ways), capped, populated -- is then reachable
 * in a test without standing up a fake repository and waiting for a promise.
 */
export const EntityTreeBrowser = ({
  projectId,
  view,
  groups,
  open,
  selected,
  loading,
  error,
  partial,
  filtered,
  onToggle,
  onSelect,
  onClose,
}: {
  /** Only so the detail panel can link into the graph view for the selected
   *  entity; nothing here fetches. */
  projectId: ProjectId
  view: GraphView
  groups: readonly EntityGroup[]
  open: ReadonlySet<string>
  selected: string | null
  loading: boolean
  error: string | null
  /** The drawing is part of a larger graph than what is shown. */
  partial: boolean
  /** A filter, not an empty project, is why `groups` is empty. Read rather
   *  than derived here, because the pane already knows which is true and a
   *  second computation of it here is a second place to get wrong. */
  filtered: boolean
  onToggle: (entityType: string) => void
  onSelect: (id: string) => void
  onClose: () => void
}) => {
  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-h-0 flex-1 flex-col">
        {partial ? (
          <p className={NOTICE}>
            Showing part of a larger graph -- search to find what is not drawn.
          </p>
        ) : null}

        {loading && groups.length === 0 ? (
          <Loading what="the entities" />
        ) : error !== null ? (
          <EmptyState heading="The entities could not be read" detail={error} />
        ) : groups.length === 0 ? (
          filtered ? (
            <EmptyState heading="Nothing matched" detail="Try a shorter term." />
          ) : (
            <EmptyState
              heading="This project is empty"
              detail="Nothing has been extracted into this project yet. Ingest a document to start building it."
            />
          )
        ) : (
          <div className="min-h-0 flex-1 overflow-auto">
            <EntityTree
              groups={groups}
              open={open}
              selected={selected}
              onToggle={onToggle}
              onSelect={onSelect}
            />
          </div>
        )}
      </div>
      {selected !== null ? (
        <GraphDetail
          projectId={projectId}
          view={view}
          selected={selected}
          onSelect={onSelect}
          showInGraphHref={projectHref(projectId, { facet: 'entity', id: selected })}
          onClose={onClose}
        />
      ) : null}
    </div>
  )
}
