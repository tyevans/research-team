import { clsx } from 'clsx'
import { useState } from 'react'

import type { AskConversationSummary, AskTranscript } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { EmptyState } from '../common/primitives.tsx'
import { AskHistory } from './AskHistory.tsx'
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
  conversationId,
  history,
  historyError,
}: {
  projectId: ProjectId
  transcript: AskTranscript
  conversationId: string | null
  /** Past conversations, for the empty state below. Empty rather than optional
   *  on a build that has none: the list is the same shape whether the project
   *  is quiet or the projection is unwired, which is what `historyError`
   *  separates. */
  history: readonly AskConversationSummary[]
  historyError: string | null
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
      // Top-aligned rather than centred once there is a list to draw: a
      // centred empty state with ten conversations under it puts the heading
      // in the middle of the page and pushes half the list off the bottom.
      <div
        className={clsx(
          'ask-thread flex min-h-0 flex-1 flex-col overflow-y-auto p-5',
          history.length === 0 ? 'items-center justify-center' : 'items-center',
        )}
      >
        <div className="flex w-full max-w-[72ch] flex-col items-center gap-6">
          <EmptyState
            heading="Nothing asked yet."
            detail="Ask about this project’s sources, topics and findings. What you ask is kept, so you can reopen it — but answers you give to its questions are not."
          />
          {/* The history list draws here and nowhere else -- see `AskHistory`
              for why the empty state is the place, and what that costs
              mid-conversation. */}
          <AskHistory projectId={projectId} conversations={history} error={historyError} />
        </div>
      </div>
    )
  }

  return (
    // `ask-thread` is the selector hook `AskView.browser.test.tsx` scrolls
    // and measures; the scrolling itself is `overflow-y-auto` beside it.
    // `padding-inline` in the old stylesheet is `px-5` here, room for the
    // scrollbar and for the turn panels to breathe.
    <div className="ask-thread min-h-0 flex-1 overflow-y-auto px-5 pt-5 pb-6">
      {/* `ask-measure` is a bare hook too: `AskView.browser.test.tsx` and
          `AskTurn.stories.tsx` both select it, so the actual cap has to live
          on the utilities beside it or the selector would find an element
          with nothing to measure. */}
      <div className="ask-measure mx-auto flex w-full max-w-[72ch] flex-col gap-6">
        {transcript.map((turn, index) => (
          <AskTurn
            key={index}
            projectId={projectId}
            turn={turn}
            conversationId={conversationId}
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
