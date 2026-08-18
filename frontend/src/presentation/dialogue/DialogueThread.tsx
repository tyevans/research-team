import { useState } from 'react'

import type { DialogueTranscript } from '@domain/dialogue/conversation.ts'
import type { DocumentBlock } from '@domain/lesson/document.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { DialogueExchange, DialogueOpening } from './DialogueExchange.tsx'

/** The dialogue in the order it happened.
 *
 *     Q1 (opening) -> A1 -> Q2 -> A2 -> Q3
 *
 * The opening question is rendered first and comes from the dialogue row: it
 * belongs to no turn, so a thread that mapped the transcript alone would draw
 * a reader answering something nobody asked. Every question after it is the
 * turn's own `blocks` -- the question that turn's answer PRODUCED -- rendered
 * below it.
 *
 * **The invariant this shape exists to hold is not "there is an element with
 * class `.dlg-pending`". It is that the page never ends on the reader's own
 * words with nothing asking them anything.** Under this order that is
 * structural rather than appended: the last thing on the page is the newest
 * question the dialogue asked, which on a fresh dialogue is the opening one
 * and otherwise is the last turn's. `.dlg-pending` survives only as a modifier
 * marking that question, because the outstanding question is not a special
 * case -- it is simply the last thing the dialogue said.
 *
 * `pendingBlocks` from the store is deliberately NOT a prop. Per
 * `app.py:3117`, the frame's `pending_blocks` is "the question being answered,
 * not the one about to be asked", so for exchange N it is turn N-1's `blocks`
 * -- already on screen, one exchange stale. A prop read in one branch only is
 * the next thing somebody wires wrongly.
 */
export const DialogueThread = ({
  projectId,
  transcript,
  openingBlocks,
  dialogueId,
}: {
  projectId: ProjectId
  transcript: DialogueTranscript
  /** The question that opened the dialogue. On the row, not on any turn --
   *  which is why it is also the one question nothing can be graded against;
   *  see `DialogueOpening`. */
  openingBlocks: readonly DocumentBlock[]
  dialogueId: string | null
}) => {
  /** Which activity folds are open, by exchange index.
   *
   * Held here rather than inside the exchange, for `AskThread`'s reason: a
   * fold owning its own state would close itself on every stream frame, which
   * is exactly while somebody is reading it. */
  const [open, setOpen] = useState<ReadonlySet<number>>(new Set())

  /** The newest turn that actually carries a question.
   *
   * Not simply the last turn: the open one has empty `blocks` until its
   * `prompt` frame lands, so mid-stream the outstanding question is the one
   * before it -- or the opening question, when the reader is answering their
   * first. `-1` means no turn has asked anything yet. */
  const newestAsked = transcript.reduce(
    (found, turn, index) => (turn.blocks.length > 0 ? index : found),
    -1,
  )

  return (
    // `dlg-thread` is a selector hook -- the scrolling is the utilities beside
    // it. The section above owns the viewport and does not scroll, so this
    // can, which is what keeps the composer on the bottom edge.
    <div
      className="dlg-thread min-h-0 flex-1 overflow-y-auto px-5 pt-5 pb-6"
      data-testid="dlg-thread"
    >
      <div className="mx-auto flex w-full max-w-[72ch] flex-col gap-6">
        {openingBlocks.length > 0 ? (
          <DialogueOpening
            blocks={openingBlocks}
            projectId={projectId}
            outstanding={newestAsked === -1}
          />
        ) : null}

        {transcript.map((turn, index) => (
          <DialogueExchange
            key={index}
            projectId={projectId}
            turn={turn}
            index={index}
            dialogueId={dialogueId}
            outstanding={index === newestAsked}
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
