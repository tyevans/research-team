import { useState } from 'react'

import type { DialogueTranscript } from '@domain/dialogue/conversation.ts'
import type { DocumentBlock } from '@domain/lesson/document.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { DialogueExchange, DialogueQuestion } from './DialogueExchange.tsx'

/** The dialogue so far, and the question still outstanding.
 *
 * **The outstanding question is rendered after the last exchange and belongs
 * to no turn.** A thread that mapped the transcript alone would end on the
 * reader's own words with nothing asking them anything, and a fresh dialogue
 * -- no turns, one opening question -- would draw an empty page. It is
 * rendered unconditionally on `pendingBlocks` rather than only when there are
 * turns, which is the shape an "append after the last exchange"
 * implementation quietly gets wrong: it renders nothing in exactly the case a
 * reader meets first.
 */
export const DialogueThread = ({
  projectId,
  transcript,
  pendingBlocks,
}: {
  projectId: ProjectId
  transcript: DialogueTranscript
  pendingBlocks: readonly DocumentBlock[]
}) => {
  /** Which activity folds are open, by exchange index.
   *
   * Held here rather than inside the exchange, for `AskThread`'s reason: a
   * fold owning its own state would close itself on every stream frame, which
   * is exactly while somebody is reading it. */
  const [open, setOpen] = useState<ReadonlySet<number>>(new Set())

  return (
    // `dlg-thread` is a selector hook -- the scrolling is the utilities beside
    // it. The section above owns the viewport and does not scroll, so this
    // can, which is what keeps the composer on the bottom edge.
    <div
      className="dlg-thread min-h-0 flex-1 overflow-y-auto px-5 pt-5 pb-6"
      data-testid="dlg-thread"
    >
      <div className="mx-auto flex w-full max-w-[72ch] flex-col gap-6">
        {transcript.map((turn, index) => (
          <DialogueExchange
            key={index}
            projectId={projectId}
            turn={turn}
            index={index}
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

        {pendingBlocks.length > 0 ? (
          <DialogueQuestion
            blocks={pendingBlocks}
            projectId={projectId}
            className="dlg-pending"
            testId="dlg-pending"
          />
        ) : null}
      </div>
    </div>
  )
}
