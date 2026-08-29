import { BULK_CAP, useBulkDispatch } from '@application/research/use-dispatch.ts'
import type { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import { Button } from '../../common/primitives.tsx'
import { Tooltip } from '../../common/Tooltip.tsx'

/** The count is on the control, and that is the safety property rather than a
 *  nicety.
 *
 * `docs/design/topic-actions-on-the-row.md` §3.3: the scope is the topics the
 * filter is currently showing, never "all", and the guarantee is that the
 * number a person reads on the button and the number of turns that start are
 * the same number *by construction* — the ids come from the array the rows are
 * rendered from (`useTopicQueue`'s `shownTopicIds`), and the route takes a list
 * rather than a word. A button reading "Find sources for every topic" over a
 * server that decided what "every" meant is two definitions that drift.
 */
export const bulkLabel = (count: number): string =>
  `Find sources for ${String(count)} ${count === 1 ? 'topic' : 'topics'}`

/** What the fan-out did, once it has done it.
 *
 * Kept on screen rather than cleared, matching `DispatchChip`'s rule for the
 * row: feedback that vanishes on the next render is how a reader concludes the
 * button did nothing.
 */
const outcome = (queued: number, unknown: number): string => {
  const started = `Started ${String(queued)} ${queued === 1 ? 'dispatch' : 'dispatches'}.`
  // The `unknown` half is said out loud rather than folded into the total.
  // The list a browser sends is what it was showing a moment ago, and a topic
  // closed or deleted in that moment comes back here instead of costing the
  // other forty-nine their dispatch -- so the count can honestly be lower than
  // the label promised, and saying so is the difference between reporting that
  // and silently starting fewer than was asked for.
  if (unknown === 0) return `${started} Watch the queue’s bar for progress.`
  return `${started} ${String(unknown)} ${unknown === 1 ? 'topic was' : 'topics were'} no longer there and ${unknown === 1 ? 'was' : 'were'} skipped.`
}

/** Send `research` at every topic the queue is currently showing.
 *
 * This is what replaces the autonomous run panel, and the argument for the
 * swap is §4.1's: a run decides for itself which topic to work and when to
 * stop, where this works the topics a person chose, in a queue a person can
 * watch and stop in one press. **It needs no progress surface of its own** —
 * the queue already renders `1 running, 11 queued` with a `Stop` beside it,
 * and every one of these dispatches lands on its own row as a chip.
 *
 * One request rather than a loop of presses, for the reason
 * `HttpTopicRepository.dispatchBulk` records: the enqueue order is the order
 * the rows are in, and a tab closed halfway through a client-side loop would
 * have started half of what the label said.
 */
export const BulkResearch = ({
  projectId,
  topicIds,
}: {
  projectId: ProjectId
  /** Exactly the rows on screen, in the order they are shown. */
  topicIds: readonly TopicId[]
}) => {
  const fanOut = useBulkDispatch(projectId)

  const count = topicIds.length
  const empty = count === 0
  const overCap = count > BULK_CAP
  const off = empty || overCap || fanOut.isPending

  // Three reasons a press is refused and three different sentences, because
  // two of them are things a person can act on and the generic "not available"
  // that would cover all three is actionable for none.
  const explanation = empty
    ? 'No topics are shown. Widen the filter first.'
    : overCap
      ? `Too many topics shown (${String(count)}). One fan-out sends at most ${String(BULK_CAP)}; narrow the filter and press it once per slice.`
      : `Sends one research turn at each of the ${String(count)} topics the filter is showing — not at every topic in the project. They queue behind each other and Stop drops the lot.`

  return (
    <div className="flex flex-col gap-[6px]">
      <Tooltip asChild explanation={explanation}>
        {/* `aria-disabled` rather than `disabled`, for the reason the row's
            verbs carry it: this control is off for a reason worth reading, and
            a `disabled` element takes neither focus nor pointer events, so the
            tooltip saying which of the three reasons applies could never open
            for a keyboard. The press is guarded in the handler instead. */}
        <Button
          aria-disabled={off}
          onClick={() => {
            if (off) return
            fanOut.mutate({ action: 'research', topicIds })
          }}
        >
          {bulkLabel(count)}
        </Button>
      </Tooltip>

      {fanOut.isError ? (
        <p className="m-0 text-xs text-k-failure">
          {fanOut.error instanceof Error ? fanOut.error.message : String(fanOut.error)}
        </p>
      ) : fanOut.data ? (
        // `role="status"`, so the outcome reaches a reader who is not looking
        // at this corner of the drawer. Every other report in this feature is
        // a chip on a row the person is already watching; this one is the only
        // place the `unknown` count is ever said, and it is said once.
        <p className="m-0 text-xs text-fg-dim" role="status">
          {outcome(fanOut.data.queued.length, fanOut.data.unknown.length)}
        </p>
      ) : null}
    </div>
  )
}
