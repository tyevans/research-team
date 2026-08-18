import type { UseQueryResult } from '@tanstack/react-query'
import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense, useId, useState } from 'react'

import { useContainer } from '@app/container-context.tsx'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { ApiError } from '@application/ports/errors.ts'
import type { TimelineWindowQuery } from '@application/ports/repositories.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { resolvedWidgetQuery } from '@application/queries/resolved-widget.ts'
import type { Timeline } from '@domain/knowledge/timeline.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import type { ExplorerSpec, TimelineWindow } from '@domain/lesson/widgets.ts'
import { EXPLORER_BACKING_READ, readExplorerQuery, varies } from '@domain/lesson/widgets.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

// Lazy for `TimelineWidget`'s reason: the axis is a drawing a reader mostly is
// not looking at, and it should be fetched when one actually meets an explorer.
const TimelineCanvas = lazy(() =>
  import('../research/TimelineCanvas.tsx').then((module) => ({ default: module.TimelineCanvas })),
)

/** A timeline the reader re-runs.
 *
 * **The one thing to know before editing this file: every reader interaction
 * costs a full pass over the tenant's entity set, twice.** `GET /timeline` is
 * two passes (`timeline_reader.py:108-115`) and is deliberately uncached, and
 * `limit` never reaches the store (`graph_reader.py:294-299`) so it does not
 * govern that cost. That is why the window control commits on blur rather than
 * on change, and why every distinct parameter set is a distinct query key
 * cached for the session. `ExplorerWidget.cost.test.tsx` fails if either half
 * is lost.
 *
 * **Two queries, one cache.** The display query carries the reader's whole
 * parameter set; the vocabulary query is the same window with no entity type,
 * and it exists because no route enumerates the known types -- the only
 * complete vocabulary available is the set present in an unfiltered response.
 * Both are keyed through `queryKeys.timeline`, so when the author fixed no
 * `entity_type` the two keys are identical and there is one request. When they
 * did fix one it is two reads on mount and two per committed window -- a moved
 * window moves both keys, because the types present inside it are not the types
 * present inside the last one. The cost test asserts both numbers rather than
 * leaving either to be discovered.
 *
 * **The vocabulary is only as complete as an uncapped response.** The server
 * caps bands, so an entity type present only past the cap is never offered and
 * a reader cannot know it exists. Fixing that needs an entity-type enumeration
 * route the design puts out of scope, so there is no honest fix here -- which
 * is why `truncated` is rendered on every result as it is in `timeline`:
 * telling the reader the answer was capped is the whole of what this build can
 * say about it.
 *
 * `attempts` is in the signature and unused, for `DefinitionWidget`'s reason:
 * every entry in `RENDERERS` takes it, and a resolved component is not
 * gradeable.
 */
export const ExplorerWidget = ({
  block,
  projectId,
}: {
  block: ComponentBlock
  attempts: AttemptsApi
  projectId?: ProjectId
}) => {
  const spec = readExplorerQuery(block)

  if (spec.over !== EXPLORER_BACKING_READ) {
    // Prose, and it names what *is* supported. The server warned rather than
    // rejected this (see `_explorer_over`), so the block is renderable and this
    // sentence is the whole of what renders -- an author who wrote
    // `over: graph` learns here that the corpus cannot be asked that yet.
    return (
      <div className="cmp-body">
        <p className="cmp-ref-note">
          This explorer asks to range over “{spec.over}”, and only “{EXPLORER_BACKING_READ}” can be
          explored in this build.
        </p>
      </div>
    )
  }

  if (!projectId) {
    // `TimelineWidget`'s `unavailable` state, drawn here rather than by
    // `ResolvedFrame` for the same reason: there is no entity reference to
    // frame, and the honest degradation is a sentence.
    return (
      <div className="cmp-body">
        <p className="cmp-ref-note">
          An explorer needs a project in scope, and this page has none.
        </p>
      </div>
    )
  }

  return (
    <div className="cmp-body">
      <p className="cmp-explorer-prompt">{spec.prompt}</p>
      <Exploring projectId={projectId} spec={spec} />
    </div>
  )
}

/** The window as the port wants it: absent keys rather than nulls, so an
 *  omitted bound stays an open end all the way to the query string and
 *  `exactOptionalPropertyTypes` is satisfied without an explicit `undefined`.
 *
 * Copied from `TimelineWidget` rather than shared. The two diverge the day
 * either grows an axis the other does not have, and a shared helper would make
 * that a change to both files. */
const asQuery = (window: TimelineWindow): TimelineWindowQuery => ({
  ...(window.entityType ? { entityType: window.entityType } : {}),
  ...(window.from ? { from: window.from } : {}),
  ...(window.to ? { to: window.to } : {}),
  ...(window.limit === null ? {} : { limit: window.limit }),
})

/** Split out so the hooks mount only once there is a project and a supported
 *  backing read to give them -- a hook cannot be called conditionally. */
const Exploring = ({ projectId, spec }: { projectId: ProjectId; spec: ExplorerSpec }) => {
  const { timelines } = useContainer()
  // The committed parameter set. Drafts live in `Controls` and arrive here only
  // on release, which is the whole cost design in one line.
  const [window, setWindow] = useState<TimelineWindow>(spec.window)

  const result = useQuery({
    queryKey: queryKeys.timeline(projectId, window),
    queryFn: () => timelines.timeline(projectId, asQuery(window)),
    ...resolvedWidgetQuery,
    // `staleTime: Infinity`, overriding the shared five minutes, and only here.
    //
    // Five minutes is right for `definition`, `graph` and `timeline`: their
    // data genuinely changes under a reader as extraction runs, and a stale
    // view of a corpus that has moved is worse than one refetch. An explorer is
    // the odd one out. The design's section 4 promises that a setting a reader
    // already tried is free *for the sitting* -- and under the shared policy a
    // reader who spends six minutes comparing four windows pays the double pass
    // again for the first one they go back to, which is exactly the promise.
    //
    // The cost, and it is real rather than theoretical: a reader who leaves an
    // explorer mounted for an hour is looking at bands that no longer reflect
    // the corpus, and there is no refresh affordance -- reloading the answer is
    // the only way back. Accepted because an explorer is a sitting: a reader
    // sweeps a few windows and moves on, and the alternative is charging them
    // twice for a window they already looked at.
    staleTime: Infinity,
  })

  // The same key builder, the same window, `entityType` dropped. Identical to
  // the display key whenever the reader has no type selected, which is what
  // makes the common case one request rather than two.
  const vocabularyWindow: TimelineWindow = { ...window, entityType: null }
  const vocabulary = useQuery({
    queryKey: queryKeys.timeline(projectId, vocabularyWindow),
    queryFn: () => timelines.timeline(projectId, asQuery(vocabularyWindow)),
    enabled: varies(spec, 'entity_type'),
    ...resolvedWidgetQuery,
    // Both queries or neither: when the two keys are identical they are one
    // cache entry, and a different `staleTime` on each would mean the entry's
    // freshness depended on which hook happened to create it.
    staleTime: Infinity,
  })

  // Sorted so the picker does not reorder itself between renders as bands
  // arrive in a different order; deduplicated because a corpus has many
  // entities per type and the picker offers types.
  const types = [
    ...new Set((vocabulary.data?.bands ?? []).map((entry) => entry.entityType).filter(Boolean)),
  ].sort()

  return (
    <>
      <Controls spec={spec} window={window} types={types} onCommit={setWindow} />
      <Result result={result} />
    </>
  )
}

/** The controls the author opened, and nothing else.
 *
 * A `<fieldset>` rather than a `<form>`: there is nothing to submit, and a form
 * inside an answer would swallow an Enter key the surrounding page may want.
 */
const Controls = ({
  spec,
  window,
  types,
  onCommit,
}: {
  spec: ExplorerSpec
  window: TimelineWindow
  types: readonly string[]
  onCommit: (next: TimelineWindow) => void
}) => {
  const [draft, setDraft] = useState({ from: window.from ?? '', to: window.to ?? '' })
  const ids = useId()

  // Commits only when something actually changed. A blur with no edit behind it
  // -- tabbing through -- must not cost a double pass, and `setState` to an
  // equal *object* is not equal to React, so the comparison is on the fields.
  const commitWindow = () => {
    const from = draft.from || null
    const to = draft.to || null
    if (from === window.from && to === window.to) return
    onCommit({ ...window, from, to })
  }

  return (
    <fieldset className="cmp-explorer-controls">
      <legend className="cmp-explorer-legend">Explore</legend>
      {varies(spec, 'entity_type') ? (
        <label className="cmp-explorer-field" htmlFor={`${ids}-type`}>
          <span>Entity type</span>
          <select
            id={`${ids}-type`}
            value={window.entityType ?? ''}
            // A select commits on change, because a change *is* the release:
            // one discrete choice, one request. Unlike a date box there is no
            // intermediate value a reader passes through on the way.
            onChange={(event) => {
              onCommit({ ...window, entityType: event.target.value || null })
            }}
          >
            <option value="">any type</option>
            {types.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {varies(spec, 'window') ? (
        <>
          <label className="cmp-explorer-field" htmlFor={`${ids}-from`}>
            <span>From</span>
            {/* `type="date"` rather than a text box, per the design's section
                4: the control produces `YYYY-MM-DD`, which is the format the
                route parses, instead of accepting free text and reporting a 422
                the reader cannot act on. */}
            <input
              id={`${ids}-from`}
              type="date"
              value={draft.from}
              onChange={(event) => {
                setDraft({ ...draft, from: event.target.value })
              }}
              onBlur={commitWindow}
            />
          </label>
          <label className="cmp-explorer-field" htmlFor={`${ids}-to`}>
            <span>To</span>
            <input
              id={`${ids}-to`}
              type="date"
              value={draft.to}
              onChange={(event) => {
                setDraft({ ...draft, to: event.target.value })
              }}
              onBlur={commitWindow}
            />
          </label>
        </>
      ) : null}
      {/* Said out loud rather than left for a reader to discover. The design's
          section 5: no filter state is serialised into the URL anywhere in this
          app, so a view cannot be linked to, and a share affordance would be
          one that does not work. */}
      <p className="cmp-explorer-note">
        What you find here cannot be linked to — take a screenshot to keep it.
      </p>
    </fieldset>
  )
}

/** The drawing and the counts. Duplicated from `TimelineWidget` for `asQuery`'s
 *  reason, and because the error prose differs: an explorer's unparseable bound
 *  is usually the *reader*'s doing rather than the author's. */
const Result = ({ result }: { result: UseQueryResult<Timeline> }) => {
  if (result.isPending) return <p className="cmp-ref-note">reading the timeline…</p>
  if (result.isError || !result.data) {
    const unparseable = result.error instanceof ApiError && result.error.status === 422
    return (
      <p className="cmp-ref-note">
        {unparseable
          ? 'One of those bounds could not be read as a date, so nothing was drawn.'
          : 'This project’s timeline could not be read just now.'}
      </p>
    )
  }

  const { bands, undatedCount, truncated } = result.data

  return (
    <>
      {/* The marker is on a wrapper that always renders rather than on the axis
          box, which does not: an explorer's empty result is a state a reader
          reaches *by exploring*, and a DOM contract that vanishes exactly then
          is one Tasks 4-6 would assert against a widget that is working. The
          box keeps its class and its height inside. */}
      <div data-explorer-widget>
        {bands.length === 0 ? (
          <p className="cmp-ref-note">Nothing dated matches that window in this project.</p>
        ) : (
          <div className="cmp-timeline-box">
            <Suspense fallback={<p className="cmp-ref-note">loading the axis…</p>}>
              {/* `onSelect` is a no-op deliberately, copying `TimelineWidget`: a
                  block inside an answer has no detail panel to open. */}
              <TimelineCanvas bands={bands} selected={null} onSelect={() => {}} />
            </Suspense>
          </div>
        )}
      </div>
      {/* Rendered on every result including the empty one, and it matters more
          here than in `timeline`: a reader narrowing a filter and watching bands
          vanish needs to know which vanished because they were excluded and
          which because the response was capped. */}
      <p className="cmp-timeline-counts">
        {bands.length} dated
        {undatedCount > 0 ? `, ${undatedCount} with no dates at all` : ''}
        {truncated ? ' — more than could be shown' : ''}
      </p>
    </>
  )
}
