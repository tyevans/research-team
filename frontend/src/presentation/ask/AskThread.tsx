import { useState } from 'react'

import type { AskActivity, AskTranscript, AskTurn } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Markdown } from '../common/content.tsx'
import { Chip, Disclosure, EmptyState } from '../common/primitives.tsx'
import { plural } from '../formatting/format.ts'
import { CitationList } from './CitationList.tsx'

/** The conversation so far: question, what was consulted, answer, sources.
 *
 * Not `Conversation.tsx`. That one renders a session's `TurnState` and carries
 * scrubbing and forking with it, and neither means anything on a page that
 * keeps nothing -- see this page's commit for the trade.
 */
export const AskThread = ({
  projectId,
  transcript,
}: {
  projectId: ProjectId
  transcript: AskTranscript
}) => {
  /** Which activity folds are open, by turn index.
   *
   * Held here rather than in each turn, the way `Segments` holds its open set:
   * a fold that lived inside the turn component would close itself every time
   * a stream frame re-rendered the transcript, which is exactly while somebody
   * is reading it. */
  const [open, setOpen] = useState<ReadonlySet<number>>(new Set())

  if (transcript.length === 0) {
    return (
      <EmptyState
        heading="Nothing asked yet."
        detail="Ask about this project’s sources, topics and findings. Nothing you ask here is written down."
      />
    )
  }

  return (
    // The one scrolling box on this page: the view does not scroll, so the
    // composer stays on the bottom edge whether the thread has one turn or
    // forty -- which is precisely when somebody wants to type the next
    // question. `pr-2` is room for the scrollbar; `pb-3` keeps the last answer
    // off the composer's top border.
    <div className="min-h-0 flex flex-auto flex-col gap-4 overflow-y-auto pr-2 pb-3">
      {transcript.map((turn, index) => (
        <Turn
          key={index}
          projectId={projectId}
          turn={turn}
          open={open.has(index)}
          onToggle={() =>
            setOpen((current) => {
              const next = new Set(current)
              if (!next.delete(index)) next.add(index)
              return next
            })
          }
        />
      ))}
    </div>
  )
}

const Turn = ({
  projectId,
  turn,
  open,
  onToggle,
}: {
  projectId: ProjectId
  turn: AskTurn
  open: boolean
  onToggle: () => void
}) => (
  <article className="flex flex-col gap-2">
    {/* The question is the reader's own words and the answer is the model's,
        told apart by weight and a rule rather than by a bubble or an avatar:
        there are only two speakers here and one of them is you, so a label per
        line would be noise on every turn. `border-solid` is spelled out
        because this build takes Tailwind's utilities without preflight, so
        nothing else sets a border style. */}
    <p className="font-semibold border-l-2 border-solid border-accent-dim pl-3 whitespace-pre-wrap text-fg">
      {turn.question}
    </p>

    {/* Above the answer and collapsed, as `Segments` collapses a tool run: the
        machinery is how the answer was reached and the answer is what was
        asked for, so it is available and never in the way. `Disclosure`
        renders nothing while closed -- it is not hidden by CSS -- which is
        what makes the jsdom test of this a real test. */}
    {turn.activity.length > 0 ? (
      <Disclosure
        className="text-sm"
        open={open}
        onToggle={onToggle}
        label={
          <span className="run-label">
            <b>Looked at {plural(turn.activity.length, 'thing')}</b>
          </span>
        }
      >
        {/* The zeroing is load-bearing rather than tidy: this build imports no
            preflight, so a bare `<ul>` keeps the user agent's margin, padding
            and bullets.

            `m-[0]` and not `m-0`, which is the trap `theme.css` describes for
            breakpoints, met on the spacing scale. `@theme` declares
            `--spacing-1` through `--spacing-6` and no `--spacing` base, so the
            `0` step has no value to compute from and `m-0` generates *no rule
            at all* -- a class that looks right, passes every gate, and does
            nothing. The arbitrary value sidesteps the scale entirely. */}
        <ul className="m-[0] flex list-none flex-col gap-1 pt-2 pr-[0] pb-[0] pl-3 text-fg-faint">
          {turn.activity.map((item) => (
            <li key={item.messageId}>
              <span className="mono">{activityName(item)}</span>
              {item.isError ? <Chip tone="fail">error</Chip> : null}
            </li>
          ))}
        </ul>
      </Disclosure>
    ) : null}

    {/* The model writes markdown, and it goes through the one sanitising
        renderer this application has -- see `Markdown`. */}
    {turn.answer ? <Markdown className="text-fg-dim" source={turn.answer} /> : null}

    {/* In the turn as well as in the page's banner. The banner is what a
        reader who has scrolled away sees; this is what says which question
        died. The only red line on the page, because a failed question is the
        one thing here that must not be mistaken for an answer. */}
    {turn.error ? <p className="font-mono text-sm text-k-failure">{turn.error}</p> : null}

    {!turn.settled ? (
      // `role="status"` rather than a bare span: the answer arrives without
      // any focus change, so a screen reader is otherwise told nothing at all
      // between the question and the answer.
      <p className="text-sm text-fg-faint" role="status">
        <span className="spinner" aria-hidden="true" />
        Thinking…
      </p>
    ) : null}

    <CitationList projectId={projectId} citations={turn.citations} />
  </article>
)

/** A tool's name if the frame carried one, its kind otherwise.
 *
 * `payload` is `unknown` by design -- the fold stores frames without
 * interpreting them -- so this narrows rather than casts. A frame whose shape
 * changes server-side degrades to "tool" here instead of throwing inside a
 * render. */
const activityName = (item: AskActivity): string => {
  if (typeof item.payload === 'object' && item.payload !== null && 'name' in item.payload) {
    const { name } = item.payload
    if (typeof name === 'string' && name) return name
  }
  return item.kind
}
