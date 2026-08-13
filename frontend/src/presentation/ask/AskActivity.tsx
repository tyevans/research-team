import type { AskActivity } from '@domain/ask/conversation.ts'

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

/** A tool's name if the frame carried one, its kind otherwise.
 *
 * `payload` is `unknown` by design -- the fold stores frames without
 * interpreting them -- so this narrows rather than casts. A frame whose shape
 * changes server-side degrades to its kind here instead of throwing inside a
 * render. */
export const activityName = (item: AskActivity): string => {
  if (typeof item.payload === 'object' && item.payload !== null && 'name' in item.payload) {
    const { name } = item.payload
    if (typeof name === 'string' && name) return name
  }
  return item.kind
}
