import type { Dispatch } from '@domain/research/dispatch.ts'
import type { TopicFocus, TopicView } from '@domain/research/topic.ts'
import type { TopicId } from '@domain/shared/identifier.ts'

import { Button, EmptyState } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
import { TopicRow } from '../entity/topic/TopicRow.tsx'

/** The slices, in the order they are offered: everything, then the one that
 *  wants a person, then what is still moving, then what is done with. */
const FOCUSES: readonly (readonly [TopicFocus, string])[] = [
  ['all', 'All'],
  ['attention', 'Needs you'],
  ['live', 'Live'],
  ['closed', 'Closed'],
]

/** Nothing has been gathered for this topic yet.
 *
 * The one thing in this feature that disables a control, and it is worth it:
 * synthesising a topic with no sources and no findings produces the model's
 * own prior knowledge presented as project findings, which is confabulation
 * that looks like a deliverable. Research is the action that fixes it, and
 * research is not built yet — so the button says why rather than offering a
 * next step it cannot take.
 */
const hasNothingToSynthesise = (topic: TopicView): boolean =>
  topic.sources === 0 && topic.findings === 0

/** `1st`, `2nd`, `3rd`, `4th`. Small enough that a dependency would be absurd. */
const ordinal = (position: number): string => {
  const tens = position % 100
  if (tens >= 11 && tens <= 13) return `${String(position)}th`
  const suffix = ['th', 'st', 'nd', 'rd'][position % 10] ?? 'th'
  return `${String(position)}${suffix}`
}

/** What one dispatch reads as on the row that produced it.
 *
 * Kept for finished dispatches rather than cleared, deliberately: a chip that
 * vanishes on the next render is how a reader concludes the button did
 * nothing. A failure in particular has to persist, because the failure and the
 * retry are the same row.
 *
 * Deliberately *not* routed through `EntityStatus`, which was the first
 * attempt. `EntityStatus` derives its tone from the status of an entity, and
 * these five words name the state of an *action* taken against one — a topic
 * whose dispatch failed is not a failed topic, and painting `failed` in the
 * entity's own status palette beside the topic's real status (`investigating`)
 * puts two chips on one row that look like they disagree about the same fact.
 */
export const DispatchChip = ({ dispatch }: { dispatch: Dispatch }) => {
  if (dispatch.status === 'queued') {
    return (
      <span className="topic-dispatch topic-dispatch-queued">
        ⧗ queued · {dispatch.position === null ? 'waiting' : ordinal(dispatch.position)}
      </span>
    )
  }
  if (dispatch.status === 'running') {
    return (
      <span className="topic-dispatch topic-dispatch-running">⟳ {dispatch.action} · running</span>
    )
  }
  if (dispatch.status === 'failed') {
    return (
      // The tooltip carries the untruncated text: the chip is clamped to one
      // line in a 320px rail, and a model's error can be a paragraph. It was a
      // `title`, which is to say the untruncated text was available to a
      // hovering mouse and to nothing else — the test that covers this is
      // named for reachability and was passing against an attribute no
      // keyboard can reach.
      <Tooltip explanation={dispatch.detail ?? 'no reason given'}>
        <span className="topic-dispatch topic-dispatch-failed">
          ✕ {dispatch.action} · failed · {dispatch.detail ?? 'no reason given'}
        </span>
      </Tooltip>
    )
  }
  if (dispatch.status === 'cancelled') {
    return <span className="topic-dispatch">⊘ {dispatch.action} · cancelled</span>
  }
  return (
    <span className="topic-dispatch topic-dispatch-done">
      ✓ {dispatch.action} · {dispatch.path ?? 'written'}
    </span>
  )
}

/** The topic queue, as markup over data it is handed.
 *
 * Holds no query, no mutation and no container: `useTopicQueue` does all of
 * that and this renders the answer. The split is what lets a story put the
 * queue in every state it has — a failed dispatch, a filter that matches
 * nothing, an empty corpus — none of which was reachable while the component
 * that drew them also fetched them.
 *
 * The rows are `entity/topic/TopicRow`, which is where the queue stops
 * spelling `status.replace('_', ' ')` for the fourth time in this codebase.
 * Two things the old row drew are deliberately gone with it:
 *
 * - **Triggers.** A row's height is now a function of its kind rather than its
 *   content, which is the contract `TopicRow` documents and L-F8 records a
 *   122px hole for breaking. Triggers are prose of unbounded length; they are
 *   rendered by `TopicDetail`, which the Manage dialog shows.
 * - **The topic's own status word, twice.** `EntityStatus` spells and tones it
 *   from the status itself, so `not_pursuing` reads the same here as it does
 *   on the landing page.
 */
export const TopicQueue = ({
  topics,
  counts,
  focus,
  search,
  dispatches,
  running,
  queuedCount,
  dispatching,
  stopping,
  onFocusChange,
  onSearchChange,
  onDispatch,
  onManage,
  onStop,
}: {
  /** Already filtered and ranked. Ranking is `byUrgency`, a domain rule, and
   *  a component that re-sorted what it was given could disagree with the
   *  counts beside it. */
  topics: readonly TopicView[]
  /** Counted over the *whole* queue, before filtering — which is what lets
   *  `counts.all` tell "nothing seeded" apart from "nothing matches". */
  counts: Record<TopicFocus, number>
  focus: TopicFocus
  search: string
  dispatches: ReadonlyMap<string, Dispatch>
  running: boolean
  queuedCount: number
  dispatching: boolean
  stopping: boolean
  onFocusChange: (focus: TopicFocus) => void
  onSearchChange: (search: string) => void
  onDispatch: (topicId: TopicId) => void
  onManage: (topicId: TopicId) => void
  onStop: () => void
}) => (
  <div className="topic-browser">
    <div className="topic-filters">
      <input
        type="search"
        className="input topic-search"
        placeholder="Filter topics"
        aria-label="Filter topics"
        value={search}
        onChange={(event) => onSearchChange(event.target.value)}
      />
      {/* A radio group, not a row of buttons: these four are one choice with
          one answer, and that is what a screen reader should be told. The
          count rides on the label so an empty slice announces itself as empty
          before it is picked. */}
      <div className="topic-focus" role="radiogroup" aria-label="Which topics to show">
        {FOCUSES.map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={focus === value}
            className={focus === value ? 'topic-focus-tab is-on' : 'topic-focus-tab'}
            onClick={() => onFocusChange(value)}
          >
            {label} <span className="topic-focus-count">{counts[value]}</span>
          </button>
        ))}
      </div>
    </div>

    {/* The aggregate, so a reader who scrolled away from the running row still
        knows something is going. One stop control here rather than a cancel
        per queued row, because cancel is per project on the server and a
        per-row control would offer an action it cannot honour. */}
    {running || queuedCount > 0 ? (
      <div className="topic-dispatch-bar">
        <span>
          {running ? '1 running' : 'none running'}
          {queuedCount > 0 ? `, ${String(queuedCount)} queued` : ''}
        </span>
        <Tooltip asChild explanation="Stop the running dispatch and drop everything queued">
          <Button small disabled={stopping} onClick={onStop}>
            Stop
          </Button>
        </Tooltip>
      </div>
    ) : null}

    {counts.all === 0 ? (
      <EmptyState heading="No topics" detail="Nothing has been seeded into this queue yet." />
    ) : topics.length === 0 ? (
      // Distinct from "No topics" above, and the distinction is the whole
      // point: that one means the queue is empty, this one means the queue has
      // work in it that the current filter is hiding.
      <EmptyState
        heading="No topics match"
        detail="Nothing in this project matches that filter. Widen it to see the rest of the queue."
      />
    ) : (
      <ul className="topic-list">
        {topics.map((topic) => {
          const dispatch = dispatches.get(topic.topicId)
          const empty = hasNothingToSynthesise(topic)
          return (
            <TopicRow
              key={topic.topicId}
              topic={topic}
              slots={{
                // The chip stays on the meta line rather than taking one of
                // its own, because a row whose height depends on whether a
                // dispatch happened is the variable-height row `TopicRow`
                // exists to rule out. It is `note` rather than part of
                // `primary` because it is read rather than pressed: it reports
                // on the verb, it is not the verb, and inside `primary` it sat
                // in the group that must never yield -- which is how a failed
                // dispatch's sentence came to push both verbs off the row.
                note: dispatch ? <DispatchChip dispatch={dispatch} /> : null,
                primary: (
                  <>
                    {/* One button rather than the split control the design
                        sketches: with one action there is nothing to split,
                        and a menu holding a single item is a click in front of
                        a button. It becomes a split button when `research` and
                        `lesson` land. */}
                    {/* `aria-disabled` rather than `disabled`, and the reason
                        is the explanation beside it: this button's sentence
                        exists *because* it is off, and a `disabled` element
                        takes neither focus nor pointer events, so the tooltip
                        it hangs on could never open. Keeping it focusable is
                        what makes "why is this off" answerable at all — the
                        old `title` was not an answer, it was an answer a mouse
                        could find. The press is guarded here instead, which is
                        the cost: nothing but this handler stops the click. */}
                    <Tooltip
                      asChild
                      explanation={
                        empty
                          ? 'Nothing gathered for this topic yet'
                          : 'Write down what this project understands about this topic'
                      }
                    >
                      <Button
                        small
                        className="topic-dispatch-button"
                        aria-disabled={empty || dispatching || dispatch?.status === 'queued'}
                        onClick={() => {
                          if (empty || dispatching || dispatch?.status === 'queued') return
                          onDispatch(topic.topicId)
                        }}
                      >
                        Write understanding
                      </Button>
                    </Tooltip>
                  </>
                ),
                overflow: [
                  <Button small key="manage" onClick={() => onManage(topic.topicId)}>
                    Manage
                  </Button>,
                ],
              }}
            />
          )
        })}
      </ul>
    )}
  </div>
)
