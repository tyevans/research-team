/** How a log entry is classified for colour and for reading.
 *
 * The backend names events in PascalCase and adds to that set freely, so this
 * buckets by substring rather than enumerating: an event type introduced later
 * gets a sane colour instead of vanishing into a default. The order of the
 * tests is the specification — housekeeping first, so nothing generic claims a
 * compaction, and failure before session so a `SessionFailed` reads as a
 * failure.
 */
export type EventKind =
  | 'compaction'
  | 'failure'
  | 'session'
  | 'tool'
  | 'file'
  | 'message'
  | 'turn'
  | 'other'

const RULES: ReadonlyArray<readonly [fragment: string, kind: EventKind]> = [
  ['compact', 'compaction'],
  ['fail', 'failure'],
  ['error', 'failure'],
  ['fork', 'session'],
  ['session', 'session'],
  ['tool', 'tool'],
  ['file', 'file'],
  ['message', 'message'],
  ['turn', 'turn'],
]

export const classifyEventType = (type: string | null | undefined): EventKind => {
  const needle = String(type ?? '').toLowerCase()
  for (const [fragment, kind] of RULES) {
    if (needle.includes(fragment)) return kind
  }
  return 'other'
}

/** `TurnCompleted` and `TurnFailed` both close a turn. */
export const isTurnEndType = (type: string | null | undefined): boolean => {
  const needle = String(type ?? '').toLowerCase()
  return needle.includes('turn') && (needle.includes('completed') || needle.includes('failed'))
}

export const isTurnFailedType = (type: string | null | undefined): boolean =>
  String(type ?? '')
    .toLowerCase()
    .includes('failed')

/** PascalCase rendered as prose: `ToolResultRecorded` → `tool result recorded`. */
export const humaniseEventType = (type: string | null | undefined): string =>
  String(type ?? 'Event')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .toLowerCase()
