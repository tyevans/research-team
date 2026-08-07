import clsx from 'clsx'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { readFlashcards } from '@domain/lesson/widgets.ts'

import { CmpButton, Prose } from './widgets.tsx'

export const Flashcards = ({
  block,
  attempts,
}: {
  block: ComponentBlock
  attempts: AttemptsApi
}) => {
  const deck = readFlashcards(block)
  const state = attempts.stateFor(block)

  if (deck.cards.length === 0) {
    return (
      <div className="cmp-body">
        {deck.title ? <h4 className="cmp-title">{deck.title}</h4> : null}
        <div className="cmp-empty">This deck has no cards.</div>
      </div>
    )
  }

  const index = Math.max(0, Math.min(state.card, deck.cards.length - 1))
  const card = deck.cards[index]!

  const step = (delta: number) =>
    attempts.update(block, {
      card: (index + delta + deck.cards.length) % deck.cards.length,
      // A new card always starts face up.
      flipped: false,
    })

  const flip = () => attempts.update(block, { flipped: !state.flipped })

  return (
    <div className="cmp-body">
      {deck.title ? <h4 className="cmp-title">{deck.title}</h4> : null}
      <div
        className={clsx('flash-card', state.flipped && 'flipped')}
        tabIndex={0}
        role="button"
        aria-pressed={state.flipped}
        aria-label={`${state.flipped ? 'Back' : 'Front'} of card ${index + 1} of ${
          deck.cards.length
        }. Activate to flip.`}
        onClick={flip}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            flip()
          } else if (event.key === 'ArrowRight') {
            event.preventDefault()
            step(1)
          } else if (event.key === 'ArrowLeft') {
            event.preventDefault()
            step(-1)
          }
        }}
      >
        <div className="flash-side">{state.flipped ? 'back' : 'front'}</div>
        <Prose text={state.flipped ? card.back : card.front} className="flash-text" />
      </div>
      <div className="cmp-controls">
        <CmpButton label="‹ prev" onClick={() => step(-1)} />
        <span className="cmp-count">
          {index + 1} / {deck.cards.length}
        </span>
        <CmpButton label="next ›" onClick={() => step(1)} />
        <CmpButton label={state.flipped ? 'show front' : 'flip'} onClick={flip} />
      </div>
    </div>
  )
}
