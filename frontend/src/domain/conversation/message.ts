/** One message as the conversation pane reads it.
 *
 * `content` is deliberately `unknown` at rest: the backend passes langchain's
 * shape through, which is a string on most messages and a list of typed blocks
 * on others. Flattening it is `contentText`'s job, once, rather than every
 * renderer's.
 */
export interface Message {
  readonly role: MessageRole
  readonly content: unknown
  readonly toolCalls: readonly ToolCall[]
  readonly isError: boolean
}

export type MessageRole = 'user' | 'assistant' | 'tool'

export interface ToolCall {
  readonly name: string
  readonly args: Readonly<Record<string, unknown>>
}

/** Message content flattened to text.
 *
 * A string passes through; langchain's block list is joined; anything else is
 * shown as JSON rather than as `[object Object]`, because a message shape this
 * does not recognise is still something a reader needs to see. */
export const contentText = (content: unknown): string => {
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content
      .map((block) => {
        if (typeof block === 'string') return block
        if (block && typeof block === 'object') {
          const record = block as Record<string, unknown>
          const text = record['text'] ?? record['content']
          return typeof text === 'string' ? text : ''
        }
        return ''
      })
      .filter(Boolean)
      .join('\n')
  }
  if (content === null || content === undefined) return ''
  return safeJson(content)
}

/** Pure machinery: a tool result, or a wordless assistant turn that only
 * dispatched calls. Anything carrying prose is not machinery, however many
 * calls it also made — the prose is what the conversation is actually saying,
 * and it is never what gets folded away. */
export const isToolActivity = (message: Message): boolean => {
  if (message.role === 'tool') return true
  return (
    message.role === 'assistant' && message.toolCalls.length > 0 && !contentText(message.content)
  )
}

/** The first argument worth showing beside a call name in one line.
 *
 * Prefers the argument that identifies *what* the call acted on, because that
 * is what a reader scanning a run is looking for; falls back to the first key
 * so a tool this list does not know about still says something. */
export const summariseArgs = (args: unknown): string => {
  if (!args || typeof args !== 'object') {
    return args === undefined || args === null ? '' : truncate(args, 70)
  }
  const record = args as Record<string, unknown>
  const keys = Object.keys(record)
  if (keys.length === 0) return ''
  const key = PREFERRED_ARGS.find((candidate) => keys.includes(candidate)) ?? keys[0]!
  const value = record[key]
  const shown = typeof value === 'string' ? value : safeJson(value)
  const extra = keys.length > 1 ? `  +${keys.length - 1}` : ''
  return `${key}=${truncate(shown, 60)}${extra}`
}

const PREFERRED_ARGS = ['path', 'file_path', 'filename', 'pattern', 'command', 'query'] as const

/** A call name with its argument preview: `name(key=value  +n)`, or bare.
 *
 * One function rather than each caller joining the two, because the transcript
 * row, the provisional bubble and the server's `_call_summary` in
 * `presenters.py` all have to agree — a bubble that previewed a call one way
 * and redrew it another the instant the turn committed is the flicker this
 * shape exists to avoid. */
export const callSummary = (call: { name?: string; args?: unknown }): string => {
  const name = call.name || '?'
  const summary = summariseArgs(call.args)
  return summary ? `${name}(${summary})` : name
}

export const ARG_DETAIL_LIMIT = 4000
/** How much of a call's arguments an expanded disclosure shows.
 *
 * The same bound the transcript already puts on a tool *result*, deliberately:
 * both are raw data being read for what it literally says, and a reader who
 * needs more than 4,000 characters of either is reading the wrong surface.
 * `remember` accepts 20,000 characters of `text`, so this is load-bearing
 * rather than theoretical — without it one call can outweigh the conversation
 * it sits in. */

/** A call's whole arguments, bounded, for a disclosure the reader opened.
 *
 * Distinct from `summariseArgs`, which picks one argument for a single line;
 * this shows all of them, and is only ever rendered on demand. */
export const argDetail = (args: unknown): string => truncate(safeJson(args), ARG_DETAIL_LIMIT)

/** JSON, or a description of why it is not.
 *
 * Never throws and never produces `[object Object]`: this renders tool
 * arguments and unrecognised message shapes, and both are things a reader is
 * looking at precisely because something unexpected happened. */
export const safeJson = (value: unknown): string => {
  try {
    const rendered = JSON.stringify(value, null, 2)
    if (rendered !== undefined) return rendered
  } catch {
    // Cyclic, or a value with a throwing toJSON. Fall through.
  }
  return describe(value)
}

/** A last resort for something JSON could not render.
 *
 * Objects are described by their tag rather than stringified, because
 * `[object Object]` is the one answer that tells a reader nothing at all — and
 * this function only ever runs when something has already gone unexpectedly. */
const describe = (value: unknown): string => {
  if (value === null) return 'null'
  if (value === undefined) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return value.toString()
  }
  if (typeof value === 'symbol') return value.toString()
  return `[${Object.prototype.toString.call(value)}]`
}

export const truncate = (value: unknown, limit: number): string => {
  const text =
    typeof value === 'string' ? value : value === null || value === undefined ? '' : describe(value)
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text
}
