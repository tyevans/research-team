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
      <div className="ask-thread ask-empty">
        <EmptyState
          heading="Nothing asked yet."
          detail="Ask about this project’s sources, topics and findings. Nothing you ask here is written down."
        />
      </div>
    )
  }

  return (
    <div className="ask-thread">
      <div className="ask-measure ask-thread-inner">
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
    </div>
  )
}
