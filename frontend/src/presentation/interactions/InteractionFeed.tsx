import { useState } from 'react'

import type { LoggedInteraction } from '@domain/interaction/log.ts'

import { Chip, Disclosure, EmptyState } from '../common/primitives.tsx'
import { clockTime } from '../formatting/format.ts'
import { interactionsHref, type InteractionFilters } from '../routing/routes.ts'
import { durationMs } from './duration.ts'
import { interactionProse } from './prose.tsx'

/** The rows themselves.
 *
 * Two orderings, one component. Newest first is the log as an instrument --
 * "what has happened lately" -- and ascending is the log as a story, which is
 * the only order a single visit reads in. The gap column belongs to the second
 * and is absent from the first: a gap between two rows of a stream that spans
 * every browser session is the time between two unrelated people's actions,
 * which is a number about nothing.
 *
 * **The payload is prose per kind, with the raw JSON one disclosure away.**
 * `prose.tsx` holds the renderers and the exhaustiveness check; what is here
 * is the decision that both are on the row. Prose alone would be a surface a
 * reader has to trust, and this is the surface whose entire job is that
 * nothing about the log has to be trusted.
 */
export const InteractionFeed = ({
  events,
  order,
  filters,
}: {
  events: readonly LoggedInteraction[]
  order: 'newest' | 'ascending'
  /** The window the rows were read under. Carried so a row's browser-session
   *  link can drop the other axes -- a drill-down is one visit end to end,
   *  and inheriting a kind filter into it would hide most of the story. */
  filters: InteractionFilters
}) => {
  if (events.length === 0) {
    return (
      <EmptyState
        heading="No events under this filter."
        detail={
          // Both readings named, because they are not the same problem and the
          // page cannot tell them apart from here. The health strip above can:
          // it says whether anything has ever arrived.
          <span>
            Either nothing matched, or nothing has been recorded. The health strip says which.
          </span>
        }
      />
    )
  }

  return (
    <ol className="m-0 flex list-none flex-col p-0">
      {events.map((event, index) => (
        <Row
          key={`${event.browserSessionId}:${event.seq}`}
          event={event}
          filters={filters}
          // The row before it *in reading order*, which is the row above on
          // screen. Only meaningful ascending; see the component docstring.
          gapFrom={order === 'ascending' && index > 0 ? events[index - 1] : undefined}
          // The date, drawn only where it changes. A feed shows clock times
          // because a column of full timestamps is a column nobody reads the
          // prose beside -- but then a feed spanning midnight has two rows an
          // hour apart and twenty-three hours apart, spelled identically. The
          // marker is the cheapest thing that tells them apart, and it is on
          // the row rather than in a `title`: a hover reaches a mouse and no
          // other reader.
          showDate={index === 0 || dayOf(events[index - 1]) !== dayOf(event)}
        />
      ))}
    </ol>
  )
}

const dayOf = (event: LoggedInteraction | undefined): string =>
  event === undefined ? '' : event.occurredAt.toISOString().slice(0, 10)

const Row = ({
  event,
  filters,
  gapFrom,
  showDate,
}: {
  event: LoggedInteraction
  filters: InteractionFilters
  gapFrom?: LoggedInteraction | undefined
  showDate: boolean
}) => {
  const [raw, setRaw] = useState(false)
  const iso = event.occurredAt.toISOString()
  return (
    // `border-0 border-b`, both halves, which is the pair `CLAUDE.md`'s
    // border entry prescribes: this build imports no preflight, so the three
    // sides that a directional width leaves styled and unwidthed would fall
    // back to the browser's `medium` and draw a box. `border-0` zeroes them;
    // `border-b` widens the one edge this row wants.
    <li className="flex flex-col gap-1 border-0 border-b border-line px-3 py-1">
      <div className="flex flex-wrap items-baseline gap-2">
        <time className="font-mono text-xs text-fg-faint" dateTime={iso}>
          {showDate ? `${iso.slice(0, 10)} ` : ''}
          {clockTime(iso)}
        </time>
        {gapFrom === undefined ? null : (
          <span className="font-mono text-xs text-fg-faint">
            +{durationMs(event.occurredAt.getTime() - gapFrom.occurredAt.getTime())}
          </span>
        )}
        <Chip>{event.kind}</Chip>
        <span className="font-mono text-xs text-fg-dim">{event.view}</span>
        <span className="text-sm text-fg">{interactionProse(event)}</span>
      </div>
      <div className="flex flex-wrap items-baseline gap-3 font-mono text-xs">
        <a
          href={interactionsHref({
            ...filters,
            kinds: [],
            views: [],
            browserSessionId: event.browserSessionId,
          })}
        >
          session {short(event.browserSessionId)}
        </a>
        <span className="text-fg-faint">seq {event.seq}</span>
        {event.projectId === null ? null : (
          <span className="text-fg-faint">project {short(event.projectId)}</span>
        )}
        {event.sessionId === null ? null : (
          <span className="text-fg-faint">agent session {short(event.sessionId)}</span>
        )}
        <Disclosure label="raw" open={raw} onToggle={() => setRaw(!raw)}>
          <pre className="m-0 whitespace-pre-wrap">{JSON.stringify(event.payload, null, 2)}</pre>
        </Disclosure>
      </div>
    </li>
  )
}

/** Enough of a UUID to recognise, in a column that has three of them.
 *
 * Truncated rather than wrapped: the full value is in the `href` of the
 * session link and in the raw payload disclosure, so nothing is lost, and a
 * feed of full UUIDs is a feed nobody reads the prose in. */
const short = (id: string): string => (id.length > 8 ? `${id.slice(0, 8)}…` : id)
