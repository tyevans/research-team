import type { AskTurn as Turn } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Markdown } from '../common/content.tsx'
import { AskActivityFold } from './AskActivity.tsx'
import { CitationList } from './CitationList.tsx'

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
}: {
  projectId: ProjectId
  turn: Turn
  open: boolean
  onToggle: () => void
}) => (
  <article className="ask-turn">
    <p className="ask-question">{turn.question}</p>

    <AskActivityFold activity={turn.activity} open={open} onToggle={onToggle} />

    {/* The model writes markdown, and it goes through the one sanitising
        renderer this application has -- see `Markdown`. */}
    {turn.answer ? <Markdown className="ask-answer" source={turn.answer} /> : null}

    {/* In the turn as well as in the page's banner. The banner is what a
        reader who has scrolled away sees; this is what says which question
        died. The only red on the page, because a failed question is the one
        thing here that must not be mistaken for an answer. */}
    {turn.error ? <p className="ask-turn-error">{turn.error}</p> : null}

    {!turn.settled ? (
      // `role="status"` rather than a bare span: the answer arrives with no
      // focus change, so a screen reader is otherwise told nothing at all
      // between the question and the answer.
      <p className="ask-pending" role="status">
        <span className="spinner" aria-hidden="true" />
        Thinking…
      </p>
    ) : null}

    <CitationList projectId={projectId} citations={turn.citations} />
  </article>
)
