import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'

import * as stories from './Flashcards.stories.tsx'

/** The rule a deck cannot show by standing still: a new card arrives face up.
 *
 * `step` writes `flipped: false` unconditionally, and that is a rule rather
 * than tidiness -- a deck that remembered each card's side would show a
 * learner the answer to a card they have not been asked yet. It is only
 * observable across a *transition*, so a story cannot carry it and a static
 * assertion cannot either.
 *
 * The card is `role="button"` with `aria-pressed`, so the flip state is
 * readable without touching a class name. That is also what makes the two
 * halves below a genuine pair: asserting `aria-pressed` is `true` when flipped
 * passes on a build that never resets it.
 *
 * **Proved red** by deleting `flipped: false` from `step` in `Flashcards.tsx`:
 * the wrap test fails, because the card arrives still showing its back.
 *
 * The *look* of a flipped card is not asserted here -- see
 * `flashcards.browser.test.tsx`, which is where the accent-scoping claim
 * `CLAUDE.md` records has to be measured.
 */
const { Front, Flipped, AtTheEnd, EmptyDeck } = composeStories(stories)

const card = () => screen.getByRole('button', { name: /of card/i })

it('reports a face-up card as unpressed', () => {
  render(<Front />)
  expect(card()).toHaveAttribute('aria-pressed', 'false')
})

it('reports a turned-over card as pressed', () => {
  render(<Flipped />)
  expect(card()).toHaveAttribute('aria-pressed', 'true')
})

/** The rule. Stepping off a turned-over card must land face up. */
it('turns the next card face up, even when the one before it was flipped', async () => {
  render(<AtTheEnd />)
  expect(card()).toHaveAttribute('aria-pressed', 'true')

  await userEvent.click(screen.getByRole('button', { name: 'next ›' }))

  expect(card()).toHaveAttribute('aria-pressed', 'false')
})

/** Flipping is reachable from the keyboard, which is most of what
 *  `role="button"` promises. */
it('flips on Enter', async () => {
  render(<Front />)
  card().focus()
  await userEvent.keyboard('{Enter}')
  expect(card()).toHaveAttribute('aria-pressed', 'true')
})

/** A stepper over an empty deck is a control that cannot do anything, so
 *  neither the card nor the controls are drawn. */
it('draws no card and no controls for an empty deck', () => {
  render(<EmptyDeck />)
  expect(screen.queryByRole('button', { name: /of card/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'next ›' })).not.toBeInTheDocument()
  // The component's own sentence, in full, rather than a substring. The first
  // draft matched `/no cards/i` and found two elements -- the component's
  // message and the *story's heading*, which said "no cards" too. That is the
  // second time in this series a loose matcher has been reddened by the prose
  // a story wraps around its subject (see `ontology-classes-stories.test.tsx`),
  // and the rule it teaches is worth stating once: a story is a page, its
  // headings are text, and `screen` does not know which half is the subject.
  // Assert the string the component actually renders.
  expect(screen.getByText('This deck has no cards.')).toBeInTheDocument()
})
