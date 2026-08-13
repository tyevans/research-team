import { useState } from 'react'

import type { AskTranscript, AskTurn } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Markdown } from '../common/content.tsx'
import { EmptyState } from '../common/primitives.tsx'
import { AskActivityFold } from './AskActivity.tsx'
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
    <div className="flex min-h-0 flex-auto flex-col gap-4 overflow-y-auto pr-2 pb-3">
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

    <AskActivityFold activity={turn.activity} open={open} onToggle={onToggle} />

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
