import type { AskActivity } from '@domain/ask/conversation.ts'
import { callSummary, contentText, truncate } from '@domain/conversation/message.ts'

import { Chip, Disclosure } from '../common/primitives.tsx'
import { plural } from '../formatting/format.ts'

/** What the model consulted, folded away.
 *
 * Above the answer and collapsed, as `Segments` collapses a tool run: the
 * machinery is how the answer was reached and the answer is what was asked
 * for, so it is available and never in the way. `Disclosure` renders nothing
 * while closed -- it is not hidden by CSS -- which is what makes the jsdom
 * test of this a real test rather than one that would pass against a
 * stylesheet-less DOM either way.
 *
 * `open` and `onToggle` are props rather than state because the transcript
 * re-renders on every stream frame, and a fold owning its own state would
 * close itself while somebody is reading it.
 */
/** The structural minimum both surfaces satisfy.
 *
 * Widened from `AskActivity` for the dialogue surface, which has one more
 * `kind` (`remark`) and is otherwise the same frame. Nothing below reads
 * `kind` at all -- every row is derived from `payload` -- so the narrower
 * literal union was buying nothing here and cost a second copy of this fold.
 * A cast at the dialogue call site would have been the alternative, and would
 * have hidden a real shape change the day one happens. */
export type ActivityFrame = Omit<AskActivity, 'kind'> & { readonly kind: string }

export const AskActivityFold = ({
  activity,
  open,
  onToggle,
}: {
  activity: readonly ActivityFrame[]
  open: boolean
  onToggle: () => void
}) => {
  const rows = activityRows(activity)
  if (rows.length === 0) return null

  return (
    <Disclosure
      className="text-sm"
      open={open}
      onToggle={onToggle}
      label={
        <span className="run-label">
          <b>Looked at {plural(rows.length, 'thing')}</b>
        </span>
      }
    >
      {/* Zeroed because there is no preflight: a bare `<ul>` keeps the user
          agent's margin, padding and bullets. `m-0`/`p-0` rather than plain
          CSS -- `--spacing-0` is declared, so they really do emit; see
          `AskView.browser.test.tsx`'s zeroing assertion. */}
      <ul className="m-0 flex list-none flex-col gap-1 pt-2 pr-0 pb-0 pl-3 text-fg-faint">
        {rows.map((row) => (
          <li key={row.key}>
            <span className="mono">{row.name}</span>
            {row.result ? <span className="mono"> → {row.result}</span> : null}
            {row.isError ? <Chip tone="fail">error</Chip> : null}
          </li>
        ))}
      </ul>
    </Disclosure>
  )
}

/** One line of the fold: a call, and what came back from it. */
export interface ActivityRow {
  readonly key: string
  readonly name: string
  /** `null` while a call is still running, or when the result said nothing. */
  readonly result: string | null
  readonly isError: boolean
}

export const RESULT_LIMIT = 80
/** How much of a result's first line a row shows.
 *
 * Wider than the argument preview beside it (60) because a result's first line
 * is the whole of what the row says about the result, where an argument is one
 * of several a reader can open the session transcript for. */

/** The fold's rows: one per *call*, with its result joined on.
 *
 * The frames arrive one per message -- an assistant frame carrying calls, then
 * a tool frame carrying each result -- and rendering them as they arrive is
 * what made this fold useless to read: every call appeared twice, and the
 * second appearance was the bare tool name, because a `ToolMessage` payload
 * has a `name` and no arguments. There is nothing a reader learns from
 * `read_source` on a line under `read_source(source_id=wiki-imperial-cult)`.
 *
 * The join is `data.tool_call_id` against the id of the call that asked, which
 * is the pairing the model itself uses; position is not relied on. A frame
 * with neither is not dropped -- a result whose call frame never arrived, or a
 * call still running, is the only trace of that tool run a reader has.
 */
export const activityRows = (activity: readonly ActivityFrame[]): readonly ActivityRow[] => {
  const results = new Map<string, ActivityFrame>()
  for (const item of activity) {
    const id = resultCallId(item)
    if (id !== null) results.set(id, item)
  }

  const joined = new Set<string>()
  const rows: ActivityRow[] = []
  for (const item of activity) {
    const calls = toolCalls(item)
    if (calls.length > 0) {
      for (const [index, call] of calls.entries()) {
        const result = call.id === null ? undefined : results.get(call.id)
        if (call.id !== null && result) joined.add(call.id)
        rows.push({
          key: `${item.messageId}:${call.id ?? String(index)}`,
          name: callSummary({ name: call.name, args: call.args }),
          result: result ? resultSummary(result) : null,
          isError: item.isError || (result?.isError ?? false),
        })
      }
      continue
    }
    const id = resultCallId(item)
    // Results are announced after the call that asked for them, so anything
    // joinable is already in `joined` by the time its own frame comes round.
    if (id !== null && joined.has(id)) continue
    rows.push({
      key: item.messageId,
      name: activityName(item),
      result: resultSummary(item),
      isError: item.isError,
    })
  }
  return rows
}

/** A call summary (`name(key=value  +n)`) if the frame carried one, its kind
 * otherwise.
 *
 * `payload` is `unknown` by design -- the fold stores frames without
 * interpreting them -- so this narrows rather than casts. The real payload is
 * langchain's `message_to_dict` output, `{type, data}`: a tool frame's name
 * and no arguments live at `data.name`; an assistant frame's calls live at
 * `data.tool_calls[]`, each `{name, args}`. A frame whose shape changes
 * server-side degrades to its kind here instead of throwing inside a render --
 * the same contract `callSummary` and `Segments.tsx` already rely on for the
 * session view of this data.
 *
 * Names the *first* call of a multi-call frame, which is a compromise it no
 * longer has to make on the rendering path -- `activityRows` gives every call
 * its own row. Kept because the rows that still reach this are the ones whose
 * calls could not be read at all, and a name is better than a kind. */
export const activityName = (item: ActivityFrame): string => {
  const data = frameData(item)
  if (data === null) return item.kind

  const name = data['name']
  if (typeof name === 'string' && name) return callSummary({ name })

  const [first] = toolCalls(item)
  if (first) return callSummary({ name: first.name, args: first.args })

  return item.kind
}

/** The `{type, data}` body of a frame, or `null` for a shape this cannot read. */
const frameData = (item: ActivityFrame): Record<string, unknown> | null => {
  const payload = item.payload
  if (typeof payload !== 'object' || payload === null) return null
  const data = (payload as Record<string, unknown>)['data']
  if (typeof data !== 'object' || data === null) return null
  return data as Record<string, unknown>
}

interface FrameCall {
  readonly name: string
  readonly args: unknown
  /** `null` when the model omitted one, which leaves the call unjoined rather
   *  than joined to the wrong result. */
  readonly id: string | null
}

const toolCalls = (item: ActivityFrame): readonly FrameCall[] => {
  const calls = frameData(item)?.['tool_calls']
  if (!Array.isArray(calls)) return []
  return calls.flatMap((call: unknown) => {
    if (!call || typeof call !== 'object') return []
    const record = call as Record<string, unknown>
    const name = record['name']
    if (typeof name !== 'string' || !name) return []
    const id = record['id']
    return [{ name, args: record['args'], id: typeof id === 'string' && id ? id : null }]
  })
}

const resultCallId = (item: ActivityFrame): string | null => {
  const id = frameData(item)?.['tool_call_id']
  return typeof id === 'string' && id ? id : null
}

/** What a result says, in one line.
 *
 * The first non-empty line and a count of the rest, rather than a character
 * total or a parse: every tool on this page answers in prose that leads with
 * its own header -- `12 source(s) in this project's corpus:`,
 * `wiki-cult@0-20000 of 84210 chars`, `No matching entities.` -- so the first
 * line is already the summary each tool wrote for itself, and counting the
 * rest says how much followed without pretending to know the format. Blank
 * lines are dropped before counting because they are spacing, and a reader
 * counting matches would otherwise be told the wrong number. */
const resultSummary = (item: ActivityFrame): string | null => {
  const text = contentText(frameData(item)?.['content']).trim()
  if (!text) return null
  const [first, ...rest] = text.split('\n').filter((line) => line.trim())
  if (first === undefined) return null
  const head = truncate(first, RESULT_LIMIT)
  return rest.length > 0 ? `${head}  +${plural(rest.length, 'line')}` : head
}
