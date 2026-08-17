import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'

import { useContainer } from '@app/container-context.tsx'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { ApiError } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { resolvedWidgetQuery } from '@application/queries/resolved-widget.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import type { TimelineWindow } from '@domain/lesson/widgets.ts'
import { readTimelineQuery } from '@domain/lesson/widgets.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

// Lazy for `GraphWidget`'s reason: the axis is a drawing a reader mostly is
// not looking at, and it should be fetched when one actually meets a timeline.
const TimelineCanvas = lazy(() =>
  import('../research/TimelineCanvas.tsx').then((module) => ({ default: module.TimelineCanvas })),
)

/** The project's dated entities on an axis, inside an answer.
 *
 * **Not entity-scoped, and the syntax deliberately does not imply it is.**
 * `GET /timeline` filters by type and range and has no entity or topic
 * filter, so an `entity:` field here would be one that silently did nothing
 * -- worse than the capability being absent, because the author would believe
 * they had asked for something.
 *
 * `undatedCount` and `truncated` are both rendered, and that is not dressing.
 * Most entities in a real graph carry no dates, so this is a view of a
 * minority of the corpus; a timeline that quietly drops two thirds of its
 * bands is the read-model failure this project has already had once, and
 * these counts are the only thing that shows it.
 *
 * The box has an explicit height for `GraphWidget`'s reason, measured in
 * `TimelineWidget.browser.test.tsx`.
 *
 * `attempts` is in the signature and unused, for `DefinitionWidget`'s reason:
 * every entry in `RENDERERS` takes it, and a resolved component is not
 * gradeable.
 */
export const TimelineWidget = ({
  block,
  projectId,
}: {
  block: ComponentBlock
  attempts: AttemptsApi
  projectId?: ProjectId
}) => {
  const window = readTimelineQuery(block)

  if (!projectId) {
    // The `unavailable` state, drawn here rather than by `ResolvedFrame`:
    // there is no entity reference to frame, and the honest degradation is a
    // sentence saying this page cannot look it up.
    return (
      <div className="cmp-body">
        <p className="cmp-ref-note">A timeline needs a project in scope, and this page has none.</p>
      </div>
    )
  }

  return (
    <div className="cmp-body">
      <Bands projectId={projectId} window={window} />
    </div>
  )
}

/** The window as the port wants it: absent keys rather than nulls, so an
 *  omitted bound stays an open end all the way to the query string, and
 *  `exactOptionalPropertyTypes` is satisfied without an explicit `undefined`. */
const asQuery = (window: TimelineWindow) => ({
  ...(window.entityType ? { entityType: window.entityType } : {}),
  ...(window.from ? { from: window.from } : {}),
  ...(window.to ? { to: window.to } : {}),
  ...(window.limit === null ? {} : { limit: window.limit }),
})

/** Split out so `useQuery` is mounted only once there is a project to give it
 *  -- a hook cannot be called conditionally. */
const Bands = ({ projectId, window }: { projectId: ProjectId; window: TimelineWindow }) => {
  const { timelines } = useContainer()
  const result = useQuery({
    queryKey: queryKeys.timeline(projectId, window),
    queryFn: () => timelines.timeline(projectId, asQuery(window)),
    // Measured, not reasoned, and the reasoning is in the constant: this route
    // is two full passes over the tenant's entire entity set and is uncached,
    // so a page of these must not refetch on every mount.
    ...resolvedWidgetQuery,
  })

  if (result.isPending) return <p className="cmp-ref-note">reading the timeline…</p>
  if (result.isError || !result.data) {
    // Two error sentences, not one. `/timeline` answers 422 for a `from:` or
    // `to:` it cannot parse rather than clamping it, which is unlike nearly
    // everything else these widgets call -- and an author told "this
    // project's timeline could not be read" would go looking at the corpus
    // instead of at the date they typed. Prose and no `role="alert"`,
    // matching every other failure here.
    const unparseable = result.error instanceof ApiError && result.error.status === 422
    return (
      <p className="cmp-ref-note">
        {unparseable
          ? 'One of this timeline’s bounds could not be read as a date, so nothing was drawn.'
          : 'This project’s timeline could not be read just now.'}
      </p>
    )
  }

  const { bands, undatedCount, truncated } = result.data

  return (
    <>
      {bands.length === 0 ? (
        <p className="cmp-ref-note">Nothing dated matches that window in this project.</p>
      ) : (
        <div className="cmp-timeline-box" data-timeline-widget>
          <Suspense fallback={<p className="cmp-ref-note">loading the axis…</p>}>
            {/* `onSelect` is a no-op deliberately, copying `GraphWidget`: a
                block inside an answer has no detail panel to open. Giving it
                one is a separate change with its own test. */}
            <TimelineCanvas bands={bands} selected={null} onSelect={() => {}} />
          </Suspense>
        </div>
      )}
      {/* Rendered even when `bands` is empty, deliberately: "nothing dated
          matches, and 412 entities carry no dates" is a more useful answer
          than either half alone. */}
      <p className="cmp-timeline-counts">
        {bands.length} dated
        {undatedCount > 0 ? `, ${undatedCount} with no dates at all` : ''}
        {truncated ? ' — more than could be shown' : ''}
      </p>
    </>
  )
}
