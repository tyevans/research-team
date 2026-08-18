import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { DialogueTurn } from '@domain/dialogue/conversation.ts'
import { freshAttempt, mcqResponse } from '@domain/lesson/attempt.ts'
import type { DocumentBlock } from '@domain/lesson/document.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { AskActivityFold } from '../ask/AskActivity.tsx'
import { CitationList } from '../ask/CitationList.tsx'
import { LessonDocument } from '../lesson/LessonDocument.tsx'

/** What the "answers withheld" tooltip means on this surface.
 *
 * Narrower than the ask's wording and wider than the lesson file's, because
 * this surface is the only one where both halves are true: the key never left
 * the server -- not even in the response that carried the question, which is
 * the leak Plan 2 closed -- and an attempt here is recorded against the
 * dialogue rather than thrown away. */
const DIALOGUE_WITHHELD_EXPLANATION =
  'The answer is not in what this page was given -- it never left the server -- so ' +
  'marking your attempt asks the server. What you answer here is recorded against ' +
  'this dialogue rather than discarded when you leave.'

/** Widget state for a question nothing can submit against yet.
 *
 * Deliberate and disclosed rather than quietly missing. Submitting an attempt
 * needs `{position, componentId, response}`, and the position of the question
 * a reader is CURRENTLY answering is not on the wire -- `pendingBlocks` is a
 * bare block list on the store, so the one question whose widgets matter has
 * no id to grade against. Plan 3 assigns that to nobody: the write side landed
 * in Plan 2 with no consumer, and Task 6 adds only the read side.
 *
 * The cost, stated plainly rather than hidden: an `mcq` inside a dialogue
 * question draws and does nothing at all -- `update` is a no-op, so a reader's
 * pick does not even highlight. That is worse than not drawing the widget, and
 * it is why this constant is named for what it is instead of being an inline
 * `{}` cast. The test that would fail once a real machine is wired in its
 * place is none: nothing here asserts on it, which is the other half of the
 * disclosure.
 */
export const UNGRADED: AttemptsApi = {
  stateFor: () => freshAttempt(),
  update: () => undefined,
  submit: () => Promise.resolve(),
  reset: () => undefined,
  mcqResponse,
}

/** A question, rendered the one way this surface ever renders one.
 *
 * Blocks and never a string: no server surface carries a raw prompt, because
 * the raw copy shipped the fenced component with `correct: true` in it while
 * the projection one key to its right withheld exactly that. `LessonDocument`
 * is reused rather than reimplemented -- blocks are blocks -- and it is the
 * same pipeline that already knows how to withhold a key.
 */
export const DialogueQuestion = ({
  blocks,
  projectId,
  className,
  testId,
}: {
  blocks: readonly DocumentBlock[]
  projectId: ProjectId
  className: string
  testId: string
}) => (
  <div className={className} data-testid={testId}>
    <LessonDocument
      doc={{ blocks }}
      attempts={UNGRADED}
      withheldExplanation={DIALOGUE_WITHHELD_EXPLANATION}
      projectId={projectId}
    />
  </div>
)

/** One exchange: what the dialogue asked, and what the reader answered.
 *
 * **The direction is the whole of this component's reason to exist.** `blocks`
 * is the dialogue's utterance and `reply` is the reader's, which is the
 * inverse of `AskTurn` -- and a page that reused `AskTurn` unchanged would
 * draw every dialogue with the speakers swapped and still read as a
 * conversation, just one where the reader asks all the questions. Nothing but
 * an explicit assertion notices, so there are two: which element holds which
 * text, and which one comes first in the document. Neither catches the other's
 * failure -- proved by swapping these two children, where the per-element
 * assertion still passes and only the ordering one goes red.
 */
export const DialogueExchange = ({
  projectId,
  turn,
  index,
  open,
  onToggle,
}: {
  projectId: ProjectId
  turn: DialogueTurn
  index: number
  open: boolean
  onToggle: () => void
}) => (
  // `border-0` before `border-t`: `border-solid` sets `border-style: solid` on
  // all four sides, and a side with a style but no explicit width falls back
  // to the browser's `medium` (~3px) rather than 0 -- the defect `AskTurn.tsx`
  // documents, which drew a full box where a top rule was wanted.
  <article
    className="dlg-exchange border-0 border-t border-solid border-line-soft pt-6 first:border-t-0 first:pt-0"
    data-testid={`dlg-exchange-${String(index)}`}
  >
    <DialogueQuestion
      blocks={turn.blocks}
      projectId={projectId}
      className="dlg-question"
      testId="dlg-question"
    />

    <AskActivityFold activity={turn.activity} open={open} onToggle={onToggle} />

    {/* The reader's own words, raw. Not markdown: they typed prose, and
        rendering it would turn a stray asterisk in an answer into emphasis
        the reader did not ask for. `pre-wrap` is in the stylesheet. */}
    <p className="dlg-answer" data-testid="dlg-answer">
      {turn.reply}
    </p>

    {turn.composing ? (
      // `role="status"` rather than a bare span: the next question arrives
      // with no focus change, so a screen reader is otherwise told nothing
      // between the reader's answer and it appearing.
      //
      // What it never says is *what* is being written. The `delta` frames that
      // set this carry an empty `text` deliberately -- they used to carry the
      // model's raw prose, fenced component and `correct: true` and all.
      <p className="dlg-composing" data-testid="dlg-composing" role="status">
        <span className="spinner" aria-hidden="true" /> Thinking about your answer…
      </p>
    ) : null}

    {turn.error ? <p className="m-0 font-mono text-sm text-k-failure">{turn.error}</p> : null}

    <CitationList projectId={projectId} citations={turn.citations} />
  </article>
)
