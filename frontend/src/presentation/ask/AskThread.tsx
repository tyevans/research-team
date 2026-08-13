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
    <div className="ask-thread">
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
  <article className="ask-turn">
    <p className="ask-question">{turn.question}</p>

    {/* Above the answer and collapsed, as `Segments` collapses a tool run: the
        machinery is how the answer was reached and the answer is what was
        asked for, so it is available and never in the way. `Disclosure`
        renders nothing while closed -- it is not hidden by CSS -- which is
        what makes the jsdom test of this a real test. */}
    {turn.activity.length > 0 ? (
      <Disclosure
        className="ask-activity"
        open={open}
        onToggle={onToggle}
        label={
          <span className="run-label">
            <b>Looked at {plural(turn.activity.length, 'thing')}</b>
          </span>
        }
      >
        <ul className="ask-activity-list">
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
    {turn.answer ? <Markdown className="ask-answer" source={turn.answer} /> : null}

    {/* In the turn as well as in the page's banner. The banner is what a
        reader who has scrolled away sees; this is what says which question
        died. */}
    {turn.error ? <p className="ask-error">{turn.error}</p> : null}

    {!turn.settled ? (
      // `role="status"` rather than a bare span: the answer arrives without
      // any focus change, so a screen reader is otherwise told nothing at all
      // between the question and the answer.
      <p className="ask-busy" role="status">
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
