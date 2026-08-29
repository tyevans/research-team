import clsx from 'clsx'
import { useCallback, useEffect, useRef, useState } from 'react'

import type { ActivityEntry } from '@domain/activity/activity.ts'
import { humaniseEventType } from '@domain/session/event-kind.ts'
import { EventIndex } from '@domain/session/event-index.ts'
import { isCancellation, kindOf, type LogEntry } from '@domain/session/log-entry.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { truncate } from '@domain/conversation/message.ts'

import { Disclosure, EmptyState } from '../common/primitives.tsx'
import { ProvisionalBubble } from './Provisional.tsx'
import { clockTime } from '../formatting/format.ts'

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
export const Timeline = ({ log, scrub, fresh, discarded, onSelect, onFork }: TimelineProps) => {
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
      //
      // Refused on HEAD, which is the one row with nothing in its action cell.
      // Before this the cursor moved there happily and `Enter` then did
      // nothing at all, because the fork branch is guarded on
      // `selectedIndex !== null` -- a mode that was invisible *and* inert. A
      // cursor that cannot go somewhere useless is one less thing to explain.
      if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
        event.preventDefault()
        event.stopPropagation()
        if (selectedIndex === null) return
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
      const next =
        event.key === 'ArrowDown' || event.key === 'j'
          ? Math.min(current + 1, total + 1)
          : event.key === 'ArrowUp' || event.key === 'k'
            ? Math.max(current - 1, 1)
            : event.key === 'Home'
              ? 1
              : event.key === 'End' || event.key === 'Escape'
                ? total + 1
                : null
      if (next === null) return

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
        heading="The log is empty."
        detail="Send a turn below — every message, tool call and file write lands here in order."
      />
    )
  }

  const atHead = scrub.kind === 'head'

  /** Where each log entry sits in the grid's row numbering, 0-based.
   *
   * Not the array offset: a failed turn with provisional content renders a
   * detail row beneath itself, so every entry after one is a row further down
   * than its position in `log`. `aria-rowindex` is 1-based, so the row itself
   * gets `at[i] + 1` and its detail row `at[i] + 2`.
   *
   * Computed here rather than in the row because only the grid can see the
   * entries before this one -- which is the reason the numbers were wrong for
   * as long as the detail row was an unwrapped sibling nobody counted. */
  const rowNumbers = ((): { at: readonly number[]; total: number } => {
    const at: number[] = []
    let next = 0
    for (const entry of log) {
      at.push(next)
      next += (discarded.get(entry.index)?.length ?? 0) > 0 ? 2 : 1
    }
    return { at, total: next }
  })()

  return (
    /* The grid is not itself a tab stop, and that is correct: this is a roving
       tabindex, so exactly one row carries `tabIndex={0}` and the rest carry
       `-1`. The rule cannot see a tab stop that lives on a child, so it reads
       a `grid` with a key handler and no `tabIndex` as unreachable. Adding
       `tabIndex={0}` here to satisfy it would create a second tab stop in
       front of the row that already has one.

       This is the rule pointing at genuinely correct code. The genuinely
       *wrong* code nearby was what §2 of the component-system spec calls S-D7 --
       an invisible column cursor where `→` silently changed what Enter does --
       and no lint rule found that one. It is closed: `cursor` is threaded to
       the row, rendered as `ev-cursor`, announced by `aria-activedescendant`
       and drawn by `timeline.css`. The point the comment was making outlives
       the defect, which is why it is still here -- a clean lint on this element
       was never a verdict on this component. */
    /* eslint-disable-next-line jsx-a11y/interactive-supports-focus */
    <div
      className="timeline"
      role="grid"
      id="timeline-grid"
      aria-label="event timeline"
      // Detail rows count. A failed turn carrying provisional content renders a
      // full-width row beneath its event, so the total is not `log.length` and
      // the rows after one are not at their array offset -- see `rowNumbers`.
      aria-rowcount={rowNumbers.total + 1}
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
            position={rowNumbers.at[position] ?? position}
            detailRowIndex={(rowNumbers.at[position] ?? position) + 2}
            selected={selected}
            cursor={selected ? column : null}
            future={scrub.kind === 'historical' && entry.index > scrub.at}
            fresh={fresh.has(entry.index)}
            discarded={discarded.get(entry.index)}
            onSelect={() => onSelect(ScrubPoint.at(entry.index))}
            onFork={() => onFork(entry.index)}
          />
        )
      })}

      {/* The keyboard route to every row, this one included, is the grid's own
          `onKeyDown` above -- arrows move the selection and Enter acts on it.
          The rule looks for a handler on the element carrying the `onClick`
          and finds none, because handling keys per row in a list this long is
          exactly the thing a roving tabindex exists to avoid. */}
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events */}
      <div
        className={clsx('head-marker', atHead && 'selected')}
        role="row"
        id="ev-head"
        // `rowNumbers.total`, not `log.length`: a failed turn with provisional
        // content adds a detail row above this one, and this marker is always
        // last. It read `log.length + 1` until 2026-08-23, which duplicated
        // the detail row's index on any log that had one -- caught by the
        // contiguity assertion in `timeline-stories.test.tsx`, not by eye.
        aria-rowindex={rowNumbers.total + 1}
        aria-selected={atHead}
        tabIndex={atHead ? 0 : -1}
        ref={atHead ? selectedRef : undefined}
        onClick={() => onSelect(ScrubPoint.head())}
      >
        {/* No `ev-cursor` and no `aria-activedescendant` on this row: the
            column cursor cannot reach HEAD, because HEAD's action cell is
            empty and `ArrowRight` now refuses to move there. */}
        <div className="ev-cell" role="gridcell" aria-colindex={1}>
          {atHead ? '● HEAD — live' : '○ HEAD — click to return to live'}
        </div>
        <div className="ev-cell ev-cell-act" role="gridcell" aria-colindex={2} />
      </div>
    </div>
  )
}

const TimelineRow = ({
  ref,
  entry,
  position,
  detailRowIndex,
  selected,
  cursor,
  future,
  fresh,
  discarded,
  onSelect,
  onFork,
}: {
  ref?: React.Ref<HTMLDivElement> | undefined
  entry: LogEntry
  /** This row's 1-based `aria-rowindex`. Passed in rather than derived from the
   *  array offset, because a failed turn adds a detail row beneath itself and
   *  every row after it shifts by one. */
  position: number
  /** The detail row's own index, one past this row's. */
  detailRowIndex: number
  selected: boolean
  /** Which cell the column cursor is on, or `null` on every row that is not
   *  the selected one. Threaded down rather than left in the grid's state
   *  because a cursor nothing renders is S-D7: `→` silently rearmed `Enter`
   *  from "scrub to this event" to "fork a new session", and the only way to
   *  find out which one you had was to press it. */
  cursor: Column | null
  future: boolean
  fresh: boolean
  discarded: readonly ActivityEntry[] | undefined
  onSelect: () => void
  onFork: () => void
}) => {
  const cancelled = isCancellation(entry)
  const summary = entry.summary ?? ''
  const cellId = (column: Column) => `ev-${entry.index}-c${column + 1}`

  return (
    <>
      {/* Same as the HEAD marker above: keys are handled once on the grid, not
          once per row. */}
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events */}
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
        // The row holds focus and names the cell within it that is current --
        // the same pattern `FileList` uses at listbox level, and the only way
        // to announce a column cursor without moving focus off the row and
        // losing the roving tabindex. Absent on unselected rows because a
        // cursor that is not on this row is not this row's business.
        aria-activedescendant={cursor === null ? undefined : cellId(cursor)}
        onClick={onSelect}
      >
        <div
          className={clsx('ev-cell', cursor === 0 && 'ev-cursor')}
          role="gridcell"
          id={cellId(0)}
          aria-colindex={1}
        >
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
        <div
          className={clsx('ev-cell', 'ev-cell-act', cursor === 1 && 'ev-cursor')}
          role="gridcell"
          id={cellId(1)}
          aria-colindex={2}
        >
          <button
            type="button"
            className="btn btn-ghost ev-fork"
            tabIndex={-1}
            aria-label={`Fork a new session at event ${entry.index}`}
            onClick={(event) => {
              event.stopPropagation()
              onFork()
            }}
          >
            fork here
          </button>
        </div>
      </div>
      {/* A full-width detail row, and the wrapper is what makes it legal.
          `role="grid"` requires every child of the grid to be a `row`, and this
          block is a sibling of the row above rather than a child of it -- so
          without this it is a stray element inside a grid, which is what
          `aria-required-children` reports.

          It shipped that way and nothing caught it, because a timeline only
          grows one of these when a turn has *failed with provisional content*,
          which no test and no story had ever rendered. Found on 2026-08-23 by
          giving `Timeline` a story that includes the case; the axe sweep named
          it immediately.

          Its own row rather than a third cell on the event's row: `.ev` is a
          flex row, this block is full width beneath it, and a detail row is
          the pattern grids use for exactly that. `rowIndex` is threaded from
          the grid so the numbering stays continuous through the interleaved
          rows, which is the half a reviewer would not think to check. */}
      {discarded && discarded.length > 0 ? (
        <div className="ev-detail" role="row" aria-rowindex={detailRowIndex}>
          <div role="gridcell" aria-colindex={1}>
            <Discarded entries={discarded} />
          </div>
        </div>
      ) : null}
    </>
  )
}

/** A failed turn's provisional content: everything that streamed in before the
 *  `TurnFailed` marker, with nothing else to show for it.
 *
 * Ephemeral — gone on reload — which the summary says plainly rather than
 * letting a reader mistake it for part of the record. */
const Discarded = ({ entries }: { entries: readonly ActivityEntry[] }) => {
  // `Disclosure` rather than the `<details>` this was, so the session view has
  // one fold implementation and not two. The state is local because nothing
  // outside needs to drive it; what phase 2 buys here is that the open state
  // is *ownable* from above, not that anything owns it today.
  //
  // The find-in-page loss §9 records applies and is accepted: a browser can no
  // longer open this fold to reveal a match. It is provisional content from a
  // failed turn, measured in a handful of lines and gone on reload, so nobody
  // is searching it.
  const [open, setOpen] = useState(false)
  return (
    <Disclosure
      className="discarded"
      label="discarded — not recorded"
      open={open}
      onToggle={() => {
        setOpen((was) => !was)
      }}
    >
      {/* The same bubble the live tail draws, so a discarded turn reads the
          way it read while it was still running — including its markdown,
          which this copy of the markup did not render. No tag: the fold above
          already says "discarded — not recorded", and the tag carries the
          pulsing dot, which would claim a turn is arriving that failed before
          the reader opened this. */}
      {entries.map((entry) => (
        <ProvisionalBubble key={entry.messageId} entry={entry} tag={null} />
      ))}
    </Disclosure>
  )
}
