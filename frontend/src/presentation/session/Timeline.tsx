import clsx from 'clsx'
import { useCallback, useEffect, useRef, useState } from 'react'

import { activityBody, type ActivityEntry } from '@domain/activity/activity.ts'
import { humaniseEventType } from '@domain/session/event-kind.ts'
import { EventIndex } from '@domain/session/event-index.ts'
import { isCancellation, kindOf, type LogEntry } from '@domain/session/log-entry.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { truncate } from '@domain/conversation/message.ts'

import { EmptyState } from '../common/primitives.tsx'
import { clockTime, fullTime } from '../formatting/format.ts'

/** Which column of a row holds the tab stop: the event itself, or its fork
 *  action. A roving pair, so arrowing down a hundred rows never silently
 *  carries the fork button along. */
type Column = 0 | 1

interface TimelineProps {
  log: readonly LogEntry[]
  scrub: ScrubPoint
  fresh: ReadonlyMap<EventIndex, number>
  discarded: ReadonlyMap<EventIndex, readonly ActivityEntry[]>
  onSelect: (at: ScrubPoint) => void
  onFork: (at: EventIndex) => void
}

/** The event log, as a grid rather than a listbox.
 *
 * Each row carries a primary action (scrub to it) *and* a secondary one (fork
 * here). `role="grid"` is the pattern that legitimately allows a focusable
 * control inside a row, so the fork button can be reached with the keyboard
 * instead of being hidden from assistive technology — which is what a listbox
 * would have forced.
 */
export const Timeline = ({
  log,
  scrub,
  fresh,
  discarded,
  onSelect,
  onFork,
}: TimelineProps) => {
  const [column, setColumn] = useState<Column>(0)
  const selectedRef = useRef<HTMLDivElement | null>(null)

  // Keep the selected row in view — including when the log arrives after the
  // first render, which is the common case at mount: the selection is HEAD and
  // HEAD is the last row, so a log that loads without this leaves the reader
  // looking at the top of a hundred events.
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: 'nearest' })
  }, [scrub, log.length])

  const selectedIndex = ScrubPoint.toNullable(scrub)

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const total = log.length
      if (total === 0) return

      // Column navigation stays within the focused row.
      if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
        event.preventDefault()
        event.stopPropagation()
        setColumn(event.key === 'ArrowRight' ? 1 : 0)
        return
      }

      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        event.stopPropagation()
        if (column === 1 && selectedIndex !== null) onFork(EventIndex(selectedIndex))
        else onSelect(scrub)
        return
      }

      // HEAD sits one past the last event, so it is reachable by the same keys.
      const current = selectedIndex ?? total + 1
      let next: number | null = null
      if (event.key === 'ArrowDown' || event.key === 'j') next = Math.min(current + 1, total + 1)
      else if (event.key === 'ArrowUp' || event.key === 'k') next = Math.max(current - 1, 1)
      else if (event.key === 'Home') next = 1
      else if (event.key === 'End' || event.key === 'Escape') next = total + 1
      else return

      event.preventDefault()
      // The document-level Escape handler is on the bubble phase too; without
      // this, one keypress would fold twice.
      event.stopPropagation()
      setColumn(0)
      onSelect(next > total ? ScrubPoint.head() : ScrubPoint.at(EventIndex(next)))
    },
    [column, log.length, onFork, onSelect, scrub, selectedIndex],
  )

  if (log.length === 0) {
    return (
      <EmptyState
        title="The log is empty."
        detail="Send a turn below — every message, tool call and file write lands here in order."
      />
    )
  }

  const atHead = scrub.kind === 'head'

  return (
    <div
      className="timeline"
      role="grid"
      id="timeline-grid"
      aria-label="event timeline"
      aria-rowcount={log.length + 1}
      aria-colcount={2}
      onKeyDown={onKeyDown}
    >
      {log.map((entry, position) => {
        const selected = selectedIndex === entry.index
        return (
          <TimelineRow
            key={entry.index}
            ref={selected ? selectedRef : undefined}
            entry={entry}
            position={position}
            selected={selected}
            future={scrub.kind === 'historical' && entry.index > scrub.at}
            fresh={fresh.has(entry.index)}
            discarded={discarded.get(entry.index)}
            onSelect={() => onSelect(ScrubPoint.at(entry.index))}
            onFork={() => onFork(entry.index)}
          />
        )
      })}

      <div
        className={clsx('head-marker', atHead && 'selected')}
        role="row"
        id="ev-head"
        aria-rowindex={log.length + 1}
        aria-selected={atHead}
        tabIndex={atHead ? 0 : -1}
        ref={atHead ? selectedRef : undefined}
        onClick={() => onSelect(ScrubPoint.head())}
      >
        <div className="ev-cell" role="gridcell">
          {atHead ? '● HEAD — live' : '○ HEAD — click to return to live'}
        </div>
        <div className="ev-cell ev-cell-act" role="gridcell" />
      </div>
    </div>
  )
}

const TimelineRow = ({
  ref,
  entry,
  position,
  selected,
  future,
  fresh,
  discarded,
  onSelect,
  onFork,
}: {
  ref?: React.Ref<HTMLDivElement> | undefined
  entry: LogEntry
  position: number
  selected: boolean
  future: boolean
  fresh: boolean
  discarded: readonly ActivityEntry[] | undefined
  onSelect: () => void
  onFork: () => void
}) => {
  const cancelled = isCancellation(entry)
  const summary = entry.summary ?? ''

  return (
    <>
      <div
        ref={ref}
        className={clsx(
          'ev',
          `k-${kindOf(entry)}`,
          selected && 'selected',
          future && 'future',
          entry.isError && !cancelled && 'is-error',
          fresh && 'fresh',
        )}
        role="row"
        id={`ev-${entry.index}`}
        aria-rowindex={position + 1}
        aria-selected={selected}
        // Roving tabindex: exactly one row is in the tab order at a time.
        tabIndex={selected ? 0 : -1}
        title={`${humaniseEventType(entry.type)}\n${fullTime(entry.occurredAt)}${
          summary ? `\n${summary}` : ''
        }`}
        onClick={onSelect}
      >
        <div className="ev-cell" role="gridcell">
          <span className="ev-idx">{entry.index}</span>
          <span className="ev-rail" />
          <span className="ev-main">
            <span className="ev-type">
              {humaniseEventType(entry.type)}
              {typeof entry.turnIndex === 'number' ? (
                <span className="ev-path"> · turn {entry.turnIndex}</span>
              ) : null}
            </span>
            <span className="ev-summary">
              {/* The summary stands alone — it has to, for the live feed — so a
                  file event already opens with the path. Don't print it twice. */}
              {entry.path && !summary.startsWith(entry.path) ? (
                <span className="ev-path">{`${entry.path}  `}</span>
              ) : null}
              {summary ? truncate(summary, 160) : entry.path ? '' : '—'}
            </span>
          </span>
          <span className="ev-time">{clockTime(entry.occurredAt)}</span>
        </div>
        <div className="ev-cell ev-cell-act" role="gridcell">
          <button
            type="button"
            className="btn btn-ghost ev-fork"
            tabIndex={-1}
            aria-label={`Fork a new session at event ${entry.index}`}
            title={`fork a new session at event ${entry.index}`}
            onClick={(event) => {
              event.stopPropagation()
              onFork()
            }}
          >
            fork here
          </button>
        </div>
      </div>
      {discarded && discarded.length > 0 ? <Discarded entries={discarded} /> : null}
    </>
  )
}

/** A failed turn's provisional content: everything that streamed in before the
 *  `TurnFailed` marker, with nothing else to show for it.
 *
 * Ephemeral — gone on reload — which the summary says plainly rather than
 * letting a reader mistake it for part of the record. */
const Discarded = ({ entries }: { entries: readonly ActivityEntry[] }) => (
  <details className="discarded">
    <summary>discarded — not recorded</summary>
    {entries.map((entry) => (
      <div key={entry.messageId} className={`provisional provisional-${entry.kind}`}>
        <div className="provisional-tag">in progress — not yet recorded</div>
        <div className="provisional-body">{activityBody(entry)}</div>
      </div>
    ))}
  </details>
)
