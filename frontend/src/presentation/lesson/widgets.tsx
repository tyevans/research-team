import clsx from 'clsx'

import type { AttemptState, Verdict } from '@domain/lesson/attempt.ts'

import { Markdown } from '../common/content.tsx'

/** The three shapes every widget builds from.
 *
 * Shared here rather than in the document renderer that happens to import them
 * first: a widget needs prose, a button and a verdict panel, and none of those
 * is about documents. */

/** Prose inside a component field, through the same renderer as everything
 *  else. Shared by all four widgets rather than re-derived in each. */
export const Prose = ({ text, className }: { text: string | null; className?: string }) => (
  <Markdown source={text ?? ''} className={clsx('cmp-prose', className)} />
)

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
