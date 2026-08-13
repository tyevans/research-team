import type { AskActivity } from '@domain/ask/conversation.ts'
import { callSummary } from '@domain/conversation/message.ts'

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
export const AskActivityFold = ({
  activity,
  open,
  onToggle,
}: {
  activity: readonly AskActivity[]
  open: boolean
  onToggle: () => void
}) => {
  if (activity.length === 0) return null

  return (
    <Disclosure
      className="text-sm"
      open={open}
      onToggle={onToggle}
      label={
        <span className="run-label">
          <b>Looked at {plural(activity.length, 'thing')}</b>
        </span>
      }
    >
      {/* Zeroed because there is no preflight: a bare `<ul>` keeps the user
          agent's margin, padding and bullets. `m-0`/`p-0` rather than plain
          CSS -- `--spacing-0` is declared, so they really do emit; see
          `AskView.browser.test.tsx`'s zeroing assertion. */}
      <ul className="m-0 flex list-none flex-col gap-1 pt-2 pr-0 pb-0 pl-3 text-fg-faint">
        {activity.map((item) => (
          <li key={item.messageId}>
            <span className="mono">{activityName(item)}</span>
            {item.isError ? <Chip tone="fail">error</Chip> : null}
          </li>
        ))}
      </ul>
    </Disclosure>
  )
}

/** A call summary (`name(key=value  +n)`) if the frame carried one, its kind
 * otherwise.
 *
 * `payload` is `unknown` by design -- the fold stores frames without
 * interpreting them -- so this narrows rather than casts. The real payload is
 * langchain's `message_to_dict` output, `{type, data}`: a tool frame's name
 * and no arguments live at `data.name`; an assistant frame's calls live at
 * `data.tool_calls[]`, each `{name, args}`, and only the first is shown
 * because this is a one-line-per-row fold, not the full transcript. A frame
 * whose shape changes server-side degrades to its kind here instead of
 * throwing inside a render -- the same contract `callSummary` and
 * `Segments.tsx` already rely on for the session view of this data. */
export const activityName = (item: AskActivity): string => {
  const payload = item.payload
  if (typeof payload !== 'object' || payload === null) return item.kind
  const data = (payload as Record<string, unknown>)['data']
  if (typeof data !== 'object' || data === null) return item.kind
  const record = data as Record<string, unknown>

  const name = record['name']
  if (typeof name === 'string' && name) return callSummary({ name })

  const calls = record['tool_calls']
  if (Array.isArray(calls) && calls.length > 0) {
    const call: unknown = calls[0]
    if (call && typeof call === 'object') {
      const callRecord = call as Record<string, unknown>
      const callName = callRecord['name']
      if (typeof callName === 'string' && callName) {
        return callSummary({ name: callName, args: callRecord['args'] })
      }
    }
  }

  return item.kind
}
