import { useDialogueAttempts } from '@application/dialogue/use-dialogue-attempts.ts'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { DialogueTurn } from '@domain/dialogue/conversation.ts'
import { freshAttempt, mcqResponse, type ItemProgress } from '@domain/lesson/attempt.ts'
import type { DocumentBlock } from '@domain/lesson/document.ts'
import type { ComponentId, ProjectId } from '@domain/shared/identifier.ts'

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

/** Widget state for the OPENING question alone.
 *
 * Not "the live question cannot be graded" -- that was true of an earlier
 * shape of this page and is false now. Every question a reader is answering is
 * the newest turn's `blocks`, and a turn carries the `position` the attempts
 * route matches against a `SocraticTurnRow`. The one exception is the opening
 * question: it lives on the dialogue row and belongs to no turn, so there is
 * no row to grade against and inventing a position would 404.
 *
 * The cost, stated plainly: a component in the opening question draws and does
 * nothing -- `update` is a no-op, so a pick does not even highlight. BACKLOG
 * B119 records the two ways out and recommends the cheap one, which is to stop
 * the model authoring components in a question that frames the dialogue rather
 * than tests anything. No test asserts on this, which is the other half of the
 * disclosure.
 */
const UNGRADED: AttemptsApi = {
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
 *
 * `outstanding` marks the newest question the dialogue has asked, which is the
 * one waiting on the reader. It is a modifier and not a separate component,
 * and that is the point of the chronological shape: the outstanding question
 * is not a special case, it is simply the last thing the dialogue said.
 */
export const DialogueQuestion = ({
  blocks,
  projectId,
  attempts,
  outstanding,
}: {
  blocks: readonly DocumentBlock[]
  projectId: ProjectId
  attempts: AttemptsApi
  outstanding: boolean
}) => (
  <div
    className={outstanding ? 'dlg-question dlg-pending' : 'dlg-question'}
    data-testid="dlg-question"
  >
    <LessonDocument
      doc={{ blocks }}
      attempts={attempts}
      withheldExplanation={DIALOGUE_WITHHELD_EXPLANATION}
      projectId={projectId}
    />
  </div>
)

/** The dialogue's opening question, which belongs to no turn.
 *
 * Its own component so the ungradeable case is one named place rather than a
 * branch inside the gradeable one -- and so that nothing can accidentally pass
 * `UNGRADED` to a question that has a turn behind it. */
export const DialogueOpening = ({
  blocks,
  projectId,
  outstanding,
}: {
  blocks: readonly DocumentBlock[]
  projectId: ProjectId
  outstanding: boolean
}) => (
  <DialogueQuestion
    blocks={blocks}
    projectId={projectId}
    attempts={UNGRADED}
    outstanding={outstanding}
  />
)

/** One exchange, in the order it happened: the reader's answer, then the
 *  question that answer PRODUCED.
 *
 * **The direction is the whole of this component's reason to exist, and the
 * order is the half that was got wrong first.** `blocks` is the dialogue's
 * utterance and `reply` is the reader's -- the inverse of an ask -- so a page
 * reusing `AskTurn` draws every dialogue with the speakers swapped and still
 * reads as a conversation. But a turn pairs `(reply, blocks)` where `blocks`
 * is the question the reply produced, and `app.py:3117` says the frame's
 * `pending_blocks` is "the question being answered, not the one about to be
 * asked". So drawing the question ABOVE the reply puts every question above
 * the answer that caused it rather than the one responding to it: a live
 * two-exchange dialogue reads Q2, A1, Q3, A2 with the outstanding question
 * buried in the middle. Chronological order is what makes the last thing on
 * the page the question waiting on the reader, without a special case.
 *
 * Two assertions guard this and neither subsumes the other, measured by
 * mutation on 2026-08-18 rather than reasoned. Reversing these two children --
 * the shape this page shipped in bbca2b5 -- reddens the ordering test and the
 * with-turns invariant, and leaves the per-element test green. Moving the two
 * testids onto each other's element, which is the real speakers-swapped bug,
 * reddens the per-element test and both invariants, and leaves the ORDERING
 * test green, because the document order is untouched. So the ordering
 * assertion cannot see a speaker swap and the per-element assertion cannot see
 * an order swap; deleting either ships one of the two bugs.
 */
export const DialogueExchange = ({
  projectId,
  turn,
  index,
  dialogueId,
  stored,
  outstanding,
  open,
  onToggle,
}: {
  projectId: ProjectId
  turn: DialogueTurn
  index: number
  dialogueId: string | null
  /** What the server remembers of THIS turn's widgets, or null where nothing
   *  has been loaded. Passed down rather than fetched here so that one request
   *  serves the whole thread; the exchange is handed only its own slice,
   *  because a component id is unique only within one utterance. */
  stored: ReadonlyMap<ComponentId, ItemProgress> | null
  /** Whether this turn's question is the newest thing the dialogue said. */
  outstanding: boolean
  open: boolean
  onToggle: () => void
}) => {
  // Unconditional, and the page's tests are wrapped in a `ContainerProvider`
  // rather than this being guarded by `hasComponents` to keep them working.
  // A guard added for a fixture's benefit would hide a missing provider until
  // the first question that happened to carry a widget -- which is production,
  // not the suite.
  const attempts = useDialogueAttempts(projectId, dialogueId, turn.position, stored)

  return (
    // `border-0` before `border-t`: `border-solid` sets `border-style: solid`
    // on all four sides, and a side with a style but no explicit width falls
    // back to the browser's `medium` (~3px) rather than 0 -- the defect
    // `AskTurn.tsx` documents, which drew a full box where a top rule was
    // wanted.
    <article
      className="dlg-exchange border-0 border-t border-solid border-line-soft pt-6 first:border-t-0 first:pt-0"
      data-testid={`dlg-exchange-${String(index)}`}
    >
      {/* The reader's own words, raw. Not markdown: they typed prose, and
          rendering it would turn a stray asterisk into emphasis they did not
          ask for. `pre-wrap` is in the stylesheet. */}
      <p className="dlg-answer" data-testid="dlg-answer">
        {turn.reply}
      </p>

      <AskActivityFold activity={turn.activity} open={open} onToggle={onToggle} />

      {turn.composing ? (
        // `role="status"` rather than a bare span: the next question arrives
        // with no focus change, so a screen reader is otherwise told nothing
        // between the reader's answer and it appearing.
        //
        // What it never says is *what* is being written. The `delta` frames
        // that set this carry an empty `text` deliberately -- they used to
        // carry the model's raw prose, fenced component and `correct: true`
        // and all.
        <p className="dlg-composing" data-testid="dlg-composing" role="status">
          <span className="spinner" aria-hidden="true" /> Thinking about your answer…
        </p>
      ) : null}

      {turn.error ? <p className="m-0 font-mono text-sm text-k-failure">{turn.error}</p> : null}

      {/* The question the answer above produced. Rendered only once there is
          one: an open turn has empty `blocks`, and an empty document would
          draw a bordered panel with nothing in it under every reply the
          moment it was sent. */}
      {turn.blocks.length > 0 ? (
        <DialogueQuestion
          blocks={turn.blocks}
          projectId={projectId}
          attempts={attempts}
          outstanding={outstanding}
        />
      ) : null}

      <CitationList projectId={projectId} citations={turn.citations} />
    </article>
  )
}
