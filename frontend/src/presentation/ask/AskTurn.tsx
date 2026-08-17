import { useAskAttempts } from '@application/ask/use-ask-attempts.ts'
import type { AskTurn as Turn } from '@domain/ask/conversation.ts'
import { hasComponents, type LessonDocument as Doc } from '@domain/lesson/document.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Markdown } from '../common/content.tsx'
import { LessonDocument } from '../lesson/LessonDocument.tsx'
import { AskActivityFold } from './AskActivity.tsx'
import { CitationList } from './CitationList.tsx'

/** The file wording says the answer key is "graded on the server" and "readable
 *  from the source toggle" -- both true of a lesson file, both false here. An
 *  ask turn has no source toggle, and the raw answer is not withheld from this
 *  page at all: it travels in the *same* response as `blocks`, unparsed. So the
 *  honest claim is narrower -- out of sight until the reader has tried, not out
 *  of reach -- and it is the one thing this surface disagrees with the file on. */
const ASK_WITHHELD_EXPLANATION =
  'The answer is not in what this page was given, so it cannot mark your attempt ' +
  'locally -- it asks the server. The full answer is still part of the reply that ' +
  'carried this question, so this keeps the answer out of sight until you have ' +
  'tried rather than out of reach.'

/** A widget-bearing answer, rendered through the same document pipeline the
 *  lesson reader uses. A sibling of `AskTurn` rather than a branch inside it,
 *  so `useAskAttempts` is never called conditionally -- a hook behind an `if`
 *  changes which hooks fire between renders of the same component, which React
 *  cannot recover from. */
const AskTurnWidgets = ({
  doc,
  projectId,
  conversationId,
  position,
}: {
  doc: Doc
  projectId: ProjectId
  conversationId: string | null
  position: number
}) => {
  const attempts = useAskAttempts(projectId, conversationId, position)
  return (
    <>
      <LessonDocument
        doc={doc}
        attempts={attempts}
        withheldExplanation={ASK_WITHHELD_EXPLANATION}
        projectId={projectId}
      />
      {/* The one honest difference from a lesson: nothing on this path
          persists an attempt, so reopening the conversation gives a blank
          question back. A reader who does not know this loses work and
          blames the page rather than the design. */}
      <p className="ask-widget-note">
        Answers here are not saved — reopening this conversation gives you a blank question.
      </p>
    </>
  )
}

/** One exchange: the question, what was consulted, the answer, its sources.
 *
 * The question is the reader's own words and the answer is the model's, told
 * apart by a panel rather than by a bubble or an avatar: there are only two
 * speakers here and one of them is you, so a label on every line would be
 * noise on every turn. The panel replaced a 2px left rule, which was too quiet
 * to survive a thread of a dozen turns -- the gap between turn n's answer and
 * turn n+1's question was the only separation on offer, and it read as one
 * long document.
 */
export const AskTurn = ({
  projectId,
  turn,
  open,
  onToggle,
  conversationId,
}: {
  projectId: ProjectId
  turn: Turn
  open: boolean
  onToggle: () => void
  conversationId: string | null
}) => (
  // The rule between exchanges: every turn but the first, because a 28px gap
  // was the only thing separating turn n's answer from turn n+1's question
  // and a dozen turns of that reads as one long document. `border-0` first,
  // `border-t` second: `border-solid` sets `border-style: solid` on all four
  // sides, and a side with a style but no explicit width falls back to the
  // browser's `medium` (~3px) rather than 0 -- proved by screenshot, where
  // every turn drew a full box instead of a top rule.
  <article className="flex flex-col gap-3 border-0 border-t border-solid border-line-soft pt-6 first:border-t-0 first:pt-0">
    {/* The reader's own words, in a panel. Told apart from the answer by
        ground rather than by a bubble or an avatar: there are only two
        speakers here and one of them is you, so a label on every line would
        be noise on every turn. */}
    <p className="m-0 rounded-md border border-solid border-line-soft bg-bg-panel-2 px-4 py-3 text-md whitespace-pre-wrap text-fg">
      {turn.question}
    </p>

    <AskActivityFold activity={turn.activity} open={open} onToggle={onToggle} />

    {/* The model writes markdown, and it goes through the one sanitising
        renderer this application has -- see `Markdown`. `text-fg`, not
        `text-fg-dim`: dimming the answer -- the thing the reader came for --
        was backwards; the machinery around it is what should recede.

        `hasComponents` is the same predicate `LessonDocument` uses to decide
        the same question: an answer with no widgets keeps this plain path, so
        the common case -- most answers -- grows no second render tree and no
        attempt state. */}
    {turn.answer ? (
      hasComponents({ blocks: turn.blocks }) ? (
        <AskTurnWidgets
          doc={{ blocks: turn.blocks }}
          projectId={projectId}
          conversationId={conversationId}
          position={turn.position}
        />
      ) : (
        <Markdown className="text-fg" source={turn.answer} projectId={projectId} />
      )
    ) : null}

    {/* In the turn as well as in the page's banner. The banner is what a
        reader who has scrolled away sees; this is what says which question
        died. The only red on the page, because a failed question is the one
        thing here that must not be mistaken for an answer. */}
    {turn.error ? <p className="m-0 font-mono text-sm text-k-failure">{turn.error}</p> : null}

    {!turn.settled ? (
      // `role="status"` rather than a bare span: the answer arrives with no
      // focus change, so a screen reader is otherwise told nothing at all
      // between the question and the answer.
      <p className="m-0 flex items-center gap-2 text-sm text-fg-faint" role="status">
        <span className="spinner" aria-hidden="true" />
        Thinking…
      </p>
    ) : null}

    <CitationList projectId={projectId} citations={turn.citations} />
  </article>
)
