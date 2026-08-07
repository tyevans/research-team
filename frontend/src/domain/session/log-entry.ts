import { classifyEventType, isTurnEndType, type EventKind } from './event-kind.ts'
import type { EventIndex } from './event-index.ts'

/** One row of a session's event log.
 *
 * The wire shape and the domain shape are the same here on purpose: a timeline
 * row is already a projection the server built for this reader, and wrapping it
 * again would add a layer that only renamed fields. What this type does add is
 * the derived questions the UI asks of a row, which used to be free functions
 * reaching into a plain object from four different modules.
 */
export interface LogEntry {
  readonly index: EventIndex
  readonly type: string
  readonly occurredAt: string
  readonly summary: string
  readonly path: string | null
  readonly turnIndex: number | null
  readonly isError: boolean | null
  /** Non-null only on a failed turn: `true` means somebody stopped it. */
  readonly cancelled: boolean | null
}

/** A deliberate cancellation arrives as a `TurnFailed` carrying `cancelled`.
 *
 * It is an outcome, not a crash, and must never be drawn as a failure — the
 * whole reason the backend sends the flag separately from the event type. */
export const isCancellation = (entry: LogEntry): boolean => entry.cancelled === true

/** The bucket that drives a row's colour, with cancellation taking precedence. */
export const kindOf = (entry: LogEntry): EventKind | 'cancelled' =>
  isCancellation(entry) ? 'cancelled' : classifyEventType(entry.type)

export const endsATurn = (entry: LogEntry): boolean => isTurnEndType(entry.type)

/** The most recent `TurnFailed` row, if any.
 *
 * Where catch-up's `discarded` content belongs: that buffer is "the last failed
 * turn's provisional content" server-side and carries no index of its own, so
 * the client pins it to the row a live frame would have pinned it to. */
export const lastFailedTurnIndex = (log: readonly LogEntry[]): EventIndex | null => {
  for (let i = log.length - 1; i >= 0; i -= 1) {
    const entry = log[i]
    if (!entry) continue
    const needle = entry.type.toLowerCase()
    if (needle.includes('turn') && needle.includes('failed')) return entry.index
  }
  return null
}

/** The entry at a log position, by its own index rather than by array offset.
 *
 * The two agree on a complete log and disagree on a partial one, and a partial
 * log is exactly what a tab that connected mid-session holds. */
export const entryAt = (log: readonly LogEntry[], index: EventIndex): LogEntry | null =>
  log.find((entry) => entry.index === index) ?? log[index - 1] ?? null

/** Merge a live frame into the log, in order, without duplicating a replay.
 *
 * Returns the same array reference when the frame was already known, so a
 * reconnect that replays a hundred frames costs no renders. */
export const appendEntry = (log: readonly LogEntry[], entry: LogEntry): readonly LogEntry[] => {
  if (log.some((known) => known.index === entry.index)) return log
  return [...log, entry].sort((a, b) => a.index - b.index)
}
