import { lazy, Suspense, useEffect, useMemo, useState } from 'react'

import { createTimelineStore } from '@application/research/timeline-store.ts'
import { useContainer } from '@app/container-context.tsx'
import { emptyGraph, expand, type Neighborhood } from '@domain/knowledge/graph.ts'
import type { Timeline } from '@domain/knowledge/timeline.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { EmptyState, Loading } from '../common/primitives.tsx'
import { useFrameRefresh } from '../shell/use-frame-refresh.ts'
import { GraphDetail } from './GraphDetail.tsx'

// `React.lazy` for the same reason `GraphPane` does it: a reader on a session
// transcript should not download a drawing they are not looking at.
const TimelineCanvas = lazy(() =>
  import('./TimelineCanvas.tsx').then((module) => ({ default: module.TimelineCanvas })),
)

/** The two capped/undated notices, matching `GraphPane`'s `NOTICE` rule for
 *  rule. `border-0` before the directional width is not optional: this build
 *  imports no preflight, so `border-solid` with only `border-b` set would draw
 *  the browser's ~3px default on the other three sides. */
const NOTICE =
  'm-0 border-0 border-b border-solid border-b-line-soft px-[6px] pb-[6px] pt-[4px] text-xs text-fg-dim'

/** The project's dated entities on a shared axis: what happened, and when.
 *
 * The peer of `GraphPane` rather than a route out of it. The graph answers
 * "what is connected to what" and deliberately refuses to draw `BEFORE`,
 * because it holds between nearly every pair of dated entities and collapses a
 * force-directed layout into a disc. This view answers the question that
 * refusal left open, and draws no edges at all -- on an axis, precedence is
 * where the bars sit, so a line asserting it would spend the densest relation
 * redstring can produce on information the reader already has.
 */
export const TimelinePane = ({
  projectId,
  entity,
  onEntity,
}: {
  projectId: ProjectId
  /** The selected entity, and how to change it. Owned by the route, the same
   *  arrangement `GraphPane` uses: this pane asks for a new selection and
   *  reacts to the one that comes back rather than keeping a copy beside the
   *  URL's. */
  entity: string | null
  onEntity: (id: string | null) => void
}) => {
  const { timelines, graphs } = useContainer()
  const store = useMemo(() => createTimelineStore({ timelines, projectId }), [timelines, projectId])
  const { timeline, loading, error, entityType } = store()

  // Keyed to the entity it was fetched for, rather than cleared on deselect:
  // the render guard below (`detail?.id === entity`) means stale detail for a
  // previous entity can never display, so there is nothing to clear
  // synchronously in the effect -- which is what `react-hooks/set-state-in-effect`
  // was catching in the version that called `setDetail(null)` from the branch
  // that ran when `entity` became `null`.
  const [detail, setDetail] = useState<{ id: string; hood: Neighborhood } | null>(null)

  useEffect(() => {
    void store.getState().load()
  }, [store])

  /** Redraw when extraction lands, rather than making the reader reload.
   *
   * The same `graph` frame `GraphPane` listens for: the events that add an
   * entity to the graph are the events that add a band to this, and a second
   * frame kind would be a second thing to remember to emit. Corpus frames are
   * ignored -- they ride the same ingest, and storing a document dates
   * nothing.
   */
  useFrameRefresh(
    true,
    (frame) => frame.kind === 'graph' && frame.projectId === projectId,
    () => void store.getState().load(),
  )

  /** Fetch what the selected entity connects to, so the panel can say more
   *  than the bar already did.
   *
   * Through `graphs.neighborhood` rather than a timeline-specific route: the
   * question "what is this entity" has one answer, and a second endpoint
   * returning a subset of it would be a second thing to keep true.
   */
  useEffect(() => {
    if (entity === null) return
    let cancelled = false
    void graphs
      .neighborhood(projectId, entity)
      .then((hood) => {
        if (!cancelled) setDetail({ id: entity, hood })
      })
      // Swallowed deliberately: the bar is still drawn and still correct, and
      // a failed detail fetch should not replace a working timeline with an
      // error. The panel simply does not open -- `detail` is left as
      // whatever it was, but the `detail?.id === entity` guard below means a
      // stale detail from a previous entity is never shown for this one.
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [entity, graphs, projectId])

  const types = useMemo(
    () => [...new Set(timeline.bands.map((band) => band.entityType))].sort(),
    [timeline.bands],
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 px-2 py-1">
        <label className="text-xs text-fg-dim" htmlFor="timeline-type">
          Type
        </label>
        <select
          id="timeline-type"
          className="lay-ring-inward rounded-md border border-solid border-line bg-bg-panel px-1 text-xs"
          value={entityType ?? ''}
          onChange={(event) => void store.getState().setEntityType(event.target.value || null)}
        >
          <option value="">All</option>
          {types.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
      </div>

      <TimelineBrowser
        timeline={timeline}
        loading={loading}
        error={error}
        selected={entity}
        onSelect={onEntity}
        detail={detail?.id === entity ? detail.hood : null}
      />
    </div>
  )
}

/** Everything the pane draws, as a function of what it was given.
 *
 * Split out and exported for the reason `GraphBrowser` is: every state --
 * loading, error, empty, capped, populated -- is then reachable in a test
 * without standing up a fake repository and waiting for a promise.
 */
export const TimelineBrowser = ({
  timeline,
  loading,
  error,
  selected,
  onSelect,
  detail,
}: {
  timeline: Timeline
  loading: boolean
  error: string | null
  selected: string | null
  onSelect: (id: string | null) => void
  detail: Neighborhood | null
}) => {
  if (loading && timeline.bands.length === 0) return <Loading what="the timeline" />
  if (error !== null) return <EmptyState heading="The timeline could not be read" detail={error} />

  if (timeline.bands.length === 0) {
    return (
      <EmptyState
        heading="No dated entities yet"
        // The count is what separates "nothing is dated" from "nothing was
        // extracted". Without it a reader meeting this goes looking for an
        // extraction failure that did not happen.
        detail={
          timeline.undatedCount > 0 ? `${timeline.undatedCount} entities carry no dates` : undefined
        }
      />
    )
  }

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-h-0 flex-1 flex-col">
        {timeline.undatedCount > 0 ? (
          <p className={NOTICE}>
            {timeline.undatedCount} of {timeline.undatedCount + timeline.bands.length} entities are
            undated and are not drawn
          </p>
        ) : null}
        {timeline.truncated ? (
          <p className={NOTICE}>Showing the first {timeline.bands.length}; there are more</p>
        ) : null}
        <div className="min-h-0 flex-1 overflow-auto">
          <Suspense fallback={<Loading what="the timeline canvas" />}>
            <TimelineCanvas bands={timeline.bands} selected={selected} onSelect={onSelect} />
          </Suspense>
        </div>
      </div>
      {detail !== null && selected !== null ? (
        <GraphDetail
          view={expand(emptyGraph, detail)}
          selected={selected}
          onSelect={onSelect}
          onClose={() => onSelect(null)}
        />
      ) : null}
    </div>
  )
}
