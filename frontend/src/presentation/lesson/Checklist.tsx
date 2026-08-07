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

  const tick = (index: number) => {
    const ticked = { ...state.ticked, [index]: !state.ticked[index] }
    attempts.update(block, { ticked })
    if (checklist.persist) {
      attempts.saveChecklist(
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
        {checklist.persist ? (
          <span className={clsx('cmp-hint', state.saveError && 'cmp-hint-error')}>
            {state.saveError ? `not saved: ${state.saveError}` : 'saved as you go'}
          </span>
        ) : null}
      </div>
    </div>
  )
}
