import clsx from 'clsx'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { readMcq } from '@domain/lesson/widgets.ts'

import { CmpButton, Prose, VerdictPanel } from './widgets.tsx'

export const Mcq = ({ block, attempts }: { block: ComponentBlock; attempts: AttemptsApi }) => {
  const mcq = readMcq(block)
  const state = attempts.stateFor(block)

  const pick = (option: number) => {
    if (mcq.multiple) {
      const picked = state.picked.includes(option)
        ? state.picked.filter((each) => each !== option)
        : [...state.picked, option]
      attempts.update(block, { picked })
    } else {
      attempts.update(block, { picked: [option] })
    }
  }

  return (
    <div className="cmp-body">
      <Prose text={mcq.prompt} className="cmp-prompt" />

      <div
        className="mcq-options"
        role={mcq.multiple ? 'group' : 'radiogroup'}
        aria-label="Answer options"
      >
        {mcq.options.map((option, index) => {
          const chosen = state.picked.includes(index)
          // Marking only lands after a verdict, and it marks what the *server*
          // said was right — the client was never given the key to decide it.
          const right = state.verdict?.correctOptions.includes(index) ?? false
          const mark = state.verdict ? (right ? 'right' : chosen ? 'wrong' : '') : ''

          return (
            <label key={index} className={clsx('mcq-option', mark, chosen && 'picked')}>
              <input
                type={mcq.multiple ? 'checkbox' : 'radio'}
                name={`mcq-${block.id}`}
                value={index}
                checked={chosen}
                disabled={state.verdict !== null}
                onChange={() => pick(index)}
              />
              <Prose text={option.text} className="mcq-text" />
              {mark === 'right' ? (
                <span className="mcq-mark" aria-label="correct answer">
                  ✓
                </span>
              ) : null}
              {mark === 'wrong' ? (
                <span className="mcq-mark" aria-label="your answer, incorrect">
                  ✕
                </span>
              ) : null}
            </label>
          )
        })}
      </div>

      <div className="cmp-controls">
        {/* The accent follows the one live action rather than sitting on
            whichever button is conceptually "primary". Once a verdict is in,
            submit is disabled and `try again` is the only thing a learner can
            do -- an accent-filled disabled button is then the loudest object
            on the row and the live control beside it is the quietest.

            This is a defect the button merge introduced and screenshotting
            found. `.cmp-btn.primary` drew an accent *outline*, so a disabled
            one at 45% opacity was already quiet; `.btn-accent` fills, and a
            45%-opacity amber block still outweighs a plain button next to it.
            The merge was right and this is the half of it that had to be
            looked at rather than reasoned about. */}
        <CmpButton
          primary={state.verdict === null}
          label={state.busy ? 'checking…' : 'check answer'}
          disabled={state.busy || state.verdict !== null || state.picked.length === 0}
          onClick={() =>
            void attempts.submit(block, attempts.mcqResponse(state.picked, mcq.multiple))
          }
        />
        {state.verdict ? (
          <CmpButton primary label="try again" onClick={() => attempts.reset(block)} />
        ) : null}
        {mcq.multiple && !state.verdict ? (
          <span className="cmp-hint">select every answer that applies</span>
        ) : null}
      </div>

      <VerdictPanel state={state} />
    </div>
  )
}
