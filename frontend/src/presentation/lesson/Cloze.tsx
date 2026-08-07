import clsx from 'clsx'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { activeBlank, clozeBlanks, readCloze } from '@domain/lesson/widgets.ts'

import { CmpButton, VerdictPanel } from './LessonDocument.tsx'

export const Cloze = ({ block, attempts }: { block: ComponentBlock; attempts: AttemptsApi }) => {
  const cloze = readCloze(block)
  const state = attempts.stateFor(block)
  const blanks = clozeBlanks(cloze)
  const active = activeBlank(cloze, state.typed)

  const submit = () => {
    if (state.busy || state.verdict) return
    attempts.submit(
      block,
      blanks.map((blank) => state.typed[blank.blank] ?? ''),
    )
  }

  return (
    <div className="cmp-body">
      <p className="cloze-text">
        {cloze.segments.map((segment, index) => {
          if (segment.kind === 'text') return <span key={index}>{segment.text}</span>

          const result = state.verdict?.blanks.find((each) => each.blank === segment.blank)
          return (
            <span
              key={index}
              className={clsx('cloze-slot', result && (result.correct ? 'right' : 'wrong'))}
            >
              <input
                type="text"
                className="cloze-input"
                value={state.typed[segment.blank] ?? ''}
                // Sized to the hint when there is one, so the passage does not
                // reflow the moment a learner starts typing.
                size={Math.max(10, Math.min(24, (segment.hint ?? '').length + 2))}
                // The hint goes *in* the blank rather than beside it: trailing
                // it made the passage ragged, and a hint the learner has to look
                // away from is a hint they read after guessing.
                placeholder={segment.hint ?? ''}
                aria-label={`Blank ${segment.blank + 1}${segment.hint ? `: ${segment.hint}` : ''}`}
                title={segment.hint ?? ''}
                disabled={state.verdict !== null || (cloze.oneAtATime && segment.blank > active)}
                onChange={(event) =>
                  attempts.update(block, {
                    typed: { ...state.typed, [segment.blank]: event.target.value },
                  })
                }
                onKeyDown={(event) => {
                  // Enter submits from any blank, which is what a keyboard user
                  // reaches for and what stops the mouse being required to
                  // finish the item.
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    submit()
                  }
                }}
              />
              {result && !result.correct ? (
                <span className="cloze-answer">{result.answer}</span>
              ) : null}
            </span>
          )
        })}
      </p>

      <div className="cmp-controls">
        <CmpButton
          primary
          label={state.busy ? 'checking…' : 'check answers'}
          disabled={state.busy || state.verdict !== null}
          onClick={submit}
        />
        {state.verdict ? (
          <CmpButton label="try again" onClick={() => attempts.reset(block)} />
        ) : null}
        <span className="cmp-count">
          {blanks.length} {blanks.length === 1 ? 'blank' : 'blanks'}
        </span>
      </div>

      <VerdictPanel state={state} />
    </div>
  )
}
