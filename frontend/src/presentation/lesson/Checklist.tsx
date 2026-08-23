import clsx from 'clsx'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { readChecklist } from '@domain/lesson/widgets.ts'

import { Prose } from './widgets.tsx'

export const Checklist = ({
  block,
  attempts,
}: {
  block: ComponentBlock
  attempts: AttemptsApi
}) => {
  const checklist = readChecklist(block)
  const state = attempts.stateFor(block)

  /** Whether ticks actually survive, which is two facts and not one.
   *
   * `checklist.persist` is the *author's* request, carried on the block.
   * `attempts.saveChecklist` is the *surface's* capability, and
   * `use-attempts.ts` leaves it `undefined` rather than a no-op precisely so
   * this can be asked -- `AttemptsApi.saveChecklist` says "absent where
   * checklists cannot persist. A widget whose save is a no-op should not offer
   * one, so `Checklist` reads this to decide."
   *
   * **It did not read it, and that was a live defect.** The hint below was
   * keyed on `checklist.persist` alone, so a checklist authored with
   * `persist: true` and rendered on a surface that cannot save -- an ask
   * answer or a dialogue question, both of which go through `LessonDocument`
   * with no `saveChecklist` -- drew "saved as you go" and saved nothing. The
   * optional call on line below has always been correct; the *claim* was not.
   *
   * Silent in every direction: the tick lands, the label says it is kept, and
   * a reader finds out on their next visit. Exactly the shape `CLAUDE.md`
   * describes for a silent default, with a sentence of reassurance on top. */
  const persists = checklist.persist && attempts.saveChecklist !== undefined

  const tick = (index: number) => {
    const ticked = { ...state.ticked, [index]: !state.ticked[index] }
    attempts.update(block, { ticked })
    if (checklist.persist) {
      attempts.saveChecklist?.(
        block,
        checklist.items.map((_, position) => position).filter((position) => ticked[position]),
      )
    }
  }

  const done = checklist.items.filter((_, index) => state.ticked[index]).length
  const required = checklist.items.filter((item) => item.required)
  const doneRequired = checklist.items.filter(
    (item, index) => item.required && state.ticked[index],
  ).length

  return (
    <div className="cmp-body">
      {checklist.title ? <h4 className="cmp-title">{checklist.title}</h4> : null}

      <ul className="check-list">
        {checklist.items.map((item, index) => (
          <li key={index} className={clsx('check-item', state.ticked[index] && 'done')}>
            <label className="check-label">
              <input
                type="checkbox"
                checked={state.ticked[index] ?? false}
                onChange={() => tick(index)}
              />
              <span className="check-text">{item.text}</span>
              {item.required ? <span className="check-req">required</span> : null}
            </label>
            {item.note ? <Prose text={item.note} className="check-note" /> : null}
          </li>
        ))}
      </ul>

      <div className="cmp-controls">
        <span
          className={clsx(
            'cmp-count',
            required.length > 0 && doneRequired === required.length && 'complete',
          )}
        >
          {done} of {checklist.items.length} done
          {required.length > 0 ? ` · ${doneRequired}/${required.length} required` : ''}
        </span>
        {persists ? (
          <span className={clsx('cmp-hint', state.saveError && 'cmp-hint-error')}>
            {state.saveError ? `not saved: ${state.saveError}` : 'saved as you go'}
          </span>
        ) : null}
      </div>
    </div>
  )
}
