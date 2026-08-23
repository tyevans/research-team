import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './Cloze.stories.tsx'

/** The mode that makes the widget mean anything, and the accent rule, both
 *  asserted as pairs.
 *
 * `oneAtATime` is the design: a learner reads forward instead of scanning the
 * passage for the easy gaps first. The two modes render an identical passage
 * and differ only in which inputs accept typing, so **only the pair can tell
 * them apart** -- "the first gap is enabled" is true under both.
 *
 * The accent rule is `Mcq`'s, restated here because `Cloze` was changed in the
 * same two commits and had no story. After grading, submit is disabled and the
 * retry is the only live control; an accent on the dead button points a
 * learner at something they cannot use.
 *
 * **Proved red** two ways. Setting `mode` to `all-at-once` in the
 * `OneAtATime` story reddens the disabled-later-gaps assertion and leaves the
 * `AllAtOnce` one green. Restoring `primary` unconditionally on `Cloze`'s
 * submit reddens the accent assertion alone.
 */
const { OneAtATime, AllAtOnce, Graded, GraderFailed } = composeStories(stories)

const inputs = () => [...document.body.querySelectorAll('input.cloze-input')] as HTMLInputElement[]

const accented = () =>
  [...document.body.querySelectorAll('button')]
    .filter((button) => button.className.includes('btn-accent'))
    .map((button) => ({ label: button.textContent, disabled: button.disabled }))

it('opens only the first gap while the mode is one at a time', () => {
  render(<OneAtATime />)
  const gaps = inputs()
  expect(gaps.length).toBeGreaterThan(1)
  expect(gaps[0]?.disabled).toBe(false)
  expect(gaps.slice(1).every((gap) => gap.disabled)).toBe(true)
})

/** The half that gives the first its meaning. */
it('opens every gap when the mode is all at once', () => {
  render(<AllAtOnce />)
  const gaps = inputs()
  expect(gaps.length).toBeGreaterThan(1)
  expect(gaps.every((gap) => !gap.disabled)).toBe(true)
})

/** Each gap is marked where it stands -- a cloze's whole advantage is that the
 *  answer sits where the question was, not in a summary below it. */
it('marks each gap in place once graded', () => {
  const { container } = render(<Graded />)
  expect(container.querySelectorAll('.cloze-slot.right')).toHaveLength(2)
  expect(container.querySelectorAll('.cloze-slot.wrong')).toHaveLength(1)
})

/** The accent follows the live action, which after grading is the retry. */
it('moves the accent to the retry once the passage is graded', () => {
  render(<Graded />)
  expect(accented()).toEqual([{ label: 'try again', disabled: false }])
})

/** An error is not a wrong answer, so nothing is marked. */
it('marks no gap when the grader failed', () => {
  const { container } = render(<GraderFailed />)
  expect(container.querySelectorAll('.cloze-slot.right, .cloze-slot.wrong')).toHaveLength(0)
  expect(screen.getByRole('alert')).toHaveTextContent('the grader did not answer')
})
