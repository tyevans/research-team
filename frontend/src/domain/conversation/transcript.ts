import { isToolActivity, type Message } from './message.ts'

/** The conversation as segments rather than as a flat list.
 *
 * A turn that reads six files and greps twice is eight messages of machinery
 * around one sentence of reasoning; rendered flat, the machinery buries the
 * sentence. So consecutive machinery collapses into one segment that says what
 * ran and opens on demand.
 *
 * Doing the grouping here rather than in the renderer is what makes it
 * testable, and what stops the "what counts as machinery" rule from being
 * restated slightly differently in the compaction pane.
 */
export type TranscriptSegment =
  | { readonly kind: 'message'; readonly at: number; readonly message: Message }
  | { readonly kind: 'toolRun'; readonly at: number; readonly messages: readonly Message[] }

/** @param offset the index of `messages[0]` in the whole conversation, so a
 *  segment's `at` is stable across the compaction split and can key open/closed
 *  state that survives a re-render. */
export const segmentTranscript = (
  messages: readonly Message[],
  offset = 0,
): readonly TranscriptSegment[] => {
  const segments: TranscriptSegment[] = []
  let i = 0
  while (i < messages.length) {
    const message = messages[i]!
    if (!isToolActivity(message)) {
      segments.push({ kind: 'message', at: offset + i, message })
      i += 1
      continue
    }
    let j = i
    while (j < messages.length && isToolActivity(messages[j]!)) j += 1
    segments.push({ kind: 'toolRun', at: offset + i, messages: messages.slice(i, j) })
    i = j
  }
  return segments
}

export interface ToolTally {
  readonly total: number
  /** `Read ×3, Bash, Grep` — first-run order, so it reads as a trace of the run
   *  rather than as an alphabetised inventory. */
  readonly label: string
}

export const tallyTools = (messages: readonly Message[]): ToolTally => {
  const order: string[] = []
  const counts = new Map<string, number>()
  let total = 0
  for (const message of messages) {
    for (const call of message.toolCalls) {
      const name = call.name || 'tool'
      if (!counts.has(name)) order.push(name)
      counts.set(name, (counts.get(name) ?? 0) + 1)
      total += 1
    }
  }
  return {
    total,
    label: order
      .map((name) => {
        const count = counts.get(name) ?? 0
        return count > 1 ? `${name} ×${count}` : name
      })
      .join(', '),
  }
}

export const segmentHasError = (messages: readonly Message[]): boolean =>
  messages.some((message) => message.isError)
