import type { MessageId, SessionId } from '../shared/identifier.ts'
import { callSummary, contentText, truncate } from '../conversation/message.ts'

export const ACTIVITY_SUMMARY_LIMIT = 160
/** How wide a provisional bubble's call summary may get, in characters.
 *
 * Matches `SUMMARY_LIMIT` in `interfaces/web/presenters.py`, which bounds the
 * committed row this previews. Two constants rather than one sent over the
 * wire: the number is a property of how wide a row reads, and a client that
 * had to be told it could not render the bubble until the server answered. */

/** Provisional content from a turn that is still running.
 *
 * Not a log entry, and the distinction matters: it carries no index, and the
 * events it previews may never be appended at all if the turn fails. A turn
 * saves atomically, so nothing reaches the event stream while it runs — this
 * channel is the only thing a reader has to look at in the meantime, and
 * everything on it is explicitly marked as not yet recorded.
 */
export interface ActivityEntry {
  readonly messageId: MessageId
  readonly sessionId: SessionId
  readonly kind: string
  /** The delta accumulator: each frame's text is the full prose so far, not an
   *  increment, so a frame replaces rather than appends. The accumulation
   *  happens server-side, on the side that has to answer the catch-up route
   *  anyway. */
  readonly text: string | null
  readonly payload: unknown
}

/** Provisional entries in arrival order, keyed so a later frame for the same
 *  message replaces the earlier one.
 *
 * A `Map` rather than the array-plus-lookup-object this used to be: insertion
 * order is part of `Map`'s contract, which is exactly the property the pairing
 * was maintaining by hand. */
export type ActivityBuffer = ReadonlyMap<MessageId, ActivityEntry>

export const emptyActivity = (): ActivityBuffer => new Map()

export const putActivity = (buffer: ActivityBuffer, entry: ActivityEntry): ActivityBuffer =>
  new Map(buffer).set(entry.messageId, entry)

export const activityEntries = (buffer: ActivityBuffer): readonly ActivityEntry[] => [
  ...buffer.values(),
]

/** What a provisional bubble shows, and which of the two things it is.
 *
 * The `form` is what the renderer needs and the text alone cannot say. A
 * streaming assistant turn is prose the model wrote in markdown, and it should
 * read the way the recorded message it is about to become reads — through
 * `Markdown`. A tool-call summary is the `→ name(arg)` shape below, which is a
 * label this code assembled, not a document: run it through a markdown parser
 * and an argument containing `_` or `*` silently turns italic. So the
 * distinction is returned rather than re-derived by a caller sniffing the
 * string, which is how the two would drift.
 *
 * A whole-message entry clears `text` server-side and populates `payload`
 * instead, whose content and calls sit under `data` — the same nesting the
 * timeline's own summariser unwraps. Mirroring it here rather than reading
 * `payload.content`, which is always undefined. */
export interface ActivityContent {
  readonly form: 'prose' | 'calls'
  readonly text: string
}

export const activityContent = (entry: ActivityEntry): ActivityContent => {
  if (entry.text) return { form: 'prose', text: entry.text }
  const payload = entry.payload
  const data =
    payload && typeof payload === 'object'
      ? ((payload as Record<string, unknown>)['data'] as Record<string, unknown> | undefined)
      : undefined
  const calls = Array.isArray(data?.['tool_calls']) ? (data['tool_calls'] as unknown[]) : []
  if (calls.length > 0) {
    // The same "→ name(arg), name(arg)" shape the timeline uses for a
    // tool-calling message, so a provisional bubble reads like the row it is
    // about to become and does not visibly change when it does.
    const summaries = calls.map((call) => {
      const record = call && typeof call === 'object' ? (call as Record<string, unknown>) : {}
      return callSummary({
        ...(typeof record['name'] === 'string' ? { name: record['name'] } : {}),
        args: record['args'],
      })
    })
    return { form: 'calls', text: truncate(`→ ${summaries.join(', ')}`, ACTIVITY_SUMMARY_LIMIT) }
  }
  return { form: 'prose', text: contentText(data?.['content']) }
}

/** The body text alone, for callers that do not care which form it took. */
export const activityBody = (entry: ActivityEntry): string => activityContent(entry).text
