import { classifyEventType } from '../session/event-kind.ts'
import type { LogEntry } from '../session/log-entry.ts'
import type { SessionId } from '../shared/identifier.ts'

/** The last thing a session said, and the last tool it reached for.
 *
 * What the agent widget puts in a row after the status: a worker carries
 * `detail` ("turn 12"), which says a turn is running and nothing about what it
 * is doing. The transcript says that, and the console is already receiving it
 * -- every log frame rides the one SSE connection the shell holds open.
 *
 * **This is folded from frames rather than fetched.** A widget on every page
 * that asked for a transcript per running agent would be N requests per page
 * on top of the roster read, for content that is already arriving. The cost is
 * that a row is blank until its session emits something, which for an agent
 * that is *actively running* is the next few seconds -- and a blank sample
 * reads as "nothing said yet", which is true.
 */
export interface TranscriptTail {
  readonly say: string | null
  readonly tool: string | null
  /** The log position the sample came from. Kept so a replayed frame cannot
   *  overwrite a newer one: a reconnect resends the gap from the cursor, and
   *  without this the row would jump backwards to an older statement. */
  readonly at: number
}

export type TranscriptTails = ReadonlyMap<SessionId, TranscriptTail>

/** An assistant statement, as distinct from the operator's own message.
 *
 * Both classify as `message`, and showing the operator their own prompt back
 * under a heading that says an agent is running would be actively misleading.
 */
const isOperatorMessage = (type: string): boolean => type.toLowerCase().includes('user')

/** Fold one log frame into the tail for its session.
 *
 * Returns the same map when nothing changed, so a burst of frames the widget
 * does not care about -- file writes, turn boundaries -- costs no re-render.
 */
export const remember = (
  tails: TranscriptTails,
  sessionId: SessionId,
  entry: LogEntry,
): TranscriptTails => {
  const kind = classifyEventType(entry.type)
  const isSay = kind === 'message' && !isOperatorMessage(entry.type)
  const isTool = kind === 'tool'
  if (!isSay && !isTool) return tails

  const summary = entry.summary.trim()
  if (!summary) return tails

  const known = tails.get(sessionId)
  // A replay arriving behind what is already shown is dropped rather than
  // applied. `>=` rather than `>` so a re-delivery of the same index is a
  // no-op too, which keeps the map reference stable across a reconnect.
  if (known && known.at >= entry.index) return tails

  const next = new Map(tails)
  next.set(sessionId, {
    say: isSay ? summary : (known?.say ?? null),
    tool: isTool ? summary : (known?.tool ?? null),
    at: entry.index,
  })
  return next
}

/** Drop every session that is no longer running.
 *
 * What bounds this map. Without it a tab left open for a day accumulates one
 * entry per session that ever ran through it, and the widget only ever reads
 * the handful that are running now. Returns the same map when nothing was
 * dropped, for the same no-re-render reason `remember` does.
 */
export const prune = (tails: TranscriptTails, keep: ReadonlySet<SessionId>): TranscriptTails => {
  let extra = 0
  for (const sessionId of tails.keys()) if (!keep.has(sessionId)) extra += 1
  if (extra === 0) return tails

  const next = new Map<SessionId, TranscriptTail>()
  for (const [sessionId, tail] of tails) if (keep.has(sessionId)) next.set(sessionId, tail)
  return next
}

/** How much of a statement reaches the DOM.
 *
 * The row ellipsises in CSS, which is what decides how much is *seen* -- this
 * decides how much is *shipped*. A summary can be a paragraph, and thirty rows
 * holding a paragraph each is a lot of text nobody can read at one line tall.
 * Generous enough that a wide widget never runs out before the ellipsis does.
 */
export const SAMPLE_CHARS = 160

/** Collapse a statement to one line's worth of text.
 *
 * Newlines become spaces: a summary can be multi-line, and a row that must not
 * grow cannot contain one. Done here rather than in CSS because `nowrap` alone
 * would still leave the newline in the accessible name a screen reader reads.
 */
export const sample = (text: string | null): string | null => {
  if (!text) return null
  const flat = text.replace(/\s+/g, ' ').trim()
  if (!flat) return null
  return flat.length > SAMPLE_CHARS ? `${flat.slice(0, SAMPLE_CHARS)}…` : flat
}
