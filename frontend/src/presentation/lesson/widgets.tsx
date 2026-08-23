import clsx from 'clsx'

import type { AttemptState, Verdict } from '@domain/lesson/attempt.ts'

import { Markdown } from '../common/content.tsx'

/** The three shapes every widget builds from.
 *
 * Shared here rather than in the document renderer that happens to import them
 * first: a widget needs prose, a button and a verdict panel, and none of those
 * is about documents. */

/** Prose inside a component field, through the same renderer as everything
 *  else. Shared by all four widgets rather than re-derived in each.
 *
 *  Blank text draws nothing, and that is the whole of a defect: `Markdown`
 *  prints a padded grey mono "(empty file)" for empty input, which is right
 *  for a *file* and wrong inside a widget. A `compare` row shorter than its
 *  entity list is padded here with `''`, and the registry's craft note
 *  explicitly invites short rows -- so the commonest way to see "(empty file)"
 *  needed no authoring mistake at all. `Markdown` keeps the notice for
 *  `FileView` and `TopicDocuments`, where an empty file should say so.
 *
 *  What this costs: a required field the model wrote as `""` -- `mcq.prompt`
 *  -- now renders as an absence rather than as a visible complaint. The
 *  complaint moved server-side to `_blank_required`, which warns the model
 *  that wrote it through `ComponentFeedback`. Nothing tells a *reader*, and
 *  nothing can: the renderer does not know which blank was meant. */
export const Prose = ({ text, className }: { text: string | null; className?: string }) =>
  text && text.trim() ? <Markdown source={text} className={clsx('cmp-prose', className)} /> : null

export const CmpButton = ({
  label,
  onClick,
  primary,
  disabled,
}: {
  label: string
  onClick: () => void
  primary?: boolean
  disabled?: boolean
}) => (
  <button
    type="button"
    className={clsx('cmp-btn', primary && 'primary')}
    disabled={disabled}
    onClick={onClick}
  >
    {label}
  </button>
)

/** What the server said, or — before any submission — what the record already
 *  knows.
 *
 * Deliberately not a reconstructed verdict: the record holds scores, not the
 * author's feedback text, and inventing a panel from a score would put words in
 * their mouth. Answering again re-earns the real one. */
export const VerdictPanel = ({ state }: { state: AttemptState }) => {
  if (state.error) {
    return (
      <div className="cmp-error" role="alert">
        {state.error}
      </div>
    )
  }

  if (!state.verdict) {
    return (
      <div className="cmp-verdict-slot" aria-live="polite">
        {state.previouslyCorrect ? (
          <div className="cmp-earlier">
            <span className="verdict-mark">✓</span>
            <span>
              You answered this correctly
              {state.attempts > 1 ? ` after ${state.attempts} tries` : ''} before.
            </span>
          </div>
        ) : null}
      </div>
    )
  }

  return <Verdicted verdict={state.verdict} />
}

const Verdicted = ({ verdict }: { verdict: Verdict }) => (
  <div
    className={clsx('cmp-verdict', verdict.correct ? 'right' : 'wrong')}
    role="status"
    aria-live="polite"
  >
    <div className="verdict-head">
      <span className="verdict-mark">{verdict.correct ? '✓' : '✕'}</span>
      <span className="verdict-word">{verdict.correct ? 'Correct' : 'Not quite'}</span>
      {typeof verdict.score === 'number' && !verdict.correct && verdict.score > 0 ? (
        <span className="verdict-score">{Math.round(verdict.score * 100)}% of the answer</span>
      ) : null}
    </div>
    {verdict.feedback.map((line, index) => (
      <Prose key={index} text={line} className="verdict-feedback" />
    ))}
    {verdict.rationale ? (
      <div className="verdict-why">
        <div className="verdict-why-label">why</div>
        <Prose text={verdict.rationale} />
      </div>
    ) : null}
  </div>
)
