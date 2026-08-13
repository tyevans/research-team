import { useState } from 'react'

import type { AskTranscript } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { EmptyState } from '../common/primitives.tsx'
import { AskTurn } from './AskTurn.tsx'

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
        <AskTurn
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
