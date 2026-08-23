import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './Mcq.stories.tsx'

/** The `Mcq` stories render a question rather than an empty frame.
 *
 * Not ceremony. `a11y.browser.test.tsx` globs every story and would catch one
 * that *throws*, but a story that renders an empty div passes it — axe has no
 * opinion about a page with nothing on it, and the sweep's assertions are
 * about violations and passes, not about content. The `VirtualList` work in
 * this same series is the worked example of why that gap matters: a component
 * whose failure mode is "renders nothing plausible" cannot be certified by a
 * story alone.
 *
 * jsdom rather than the browser suite, deliberately. Every claim here is a
 * role or a piece of text, which `CLAUDE.md` says belongs in a `.test.tsx`
 * where it runs in a second instead of a minute. Nothing here is geometry.
 *
 * **Proved red** by emptying the shared question's `options`: the first test
 * fails with `Unable to find an element with the text: /tetrarchy/`.
 *
 * Only the first, and that is worth recording rather than rounding up. The
 * other three read the verdict panel, the alert and a *separate* option set
 * declared inside `MultipleChoice`, so emptying one array leaves them green --
 * which is the tests being independent rather than the proof being weak. A
 * single break that reddened all four would have meant they were all really
 * one assertion.
 */
const { Unanswered, Correct, GraderFailed, MultipleChoice } = composeStories(stories)

it('renders the prompt and every option', () => {
  render(<Unanswered />)
  expect(screen.getByText(/Diocletian best known for/)).toBeInTheDocument()
  expect(screen.getByText(/tetrarchy/)).toBeInTheDocument()
  expect(screen.getByText(/Abolishing the Senate/)).toBeInTheDocument()
})

/** A graded verdict reaches the page, which is the whole point of the widget.
 *
 *  Asserts the server's feedback text specifically, not merely that something
 *  rendered: a verdict panel that drew its frame and dropped the sentence
 *  would look like a working widget and tell the learner nothing. */
it('shows the feedback a correct verdict carried', () => {
  render(<Correct />)
  expect(screen.getByText(/two Augusti and two Caesars/)).toBeInTheDocument()
})

/** An error is announced as an alert, not as a verdict.
 *
 *  The distinction is the reason the story exists: a learner told "incorrect"
 *  when the grader was down has been told something false about themselves.
 *  `role="alert"` is what separates the two paths, so that is what is
 *  asserted rather than the text alone. */
it('announces a failed grader as an alert rather than a verdict', () => {
  render(<GraderFailed />)
  expect(screen.getByRole('alert')).toHaveTextContent('the grader did not answer')
})

/** The multiple-choice variant renders its own option set rather than the
 *  shared one, which is the thing a copied story body gets wrong. */
it('renders the multiple-answer question with its own options', () => {
  render(<MultipleChoice />)
  expect(screen.getByText(/choose all that apply/)).toBeInTheDocument()
  expect(screen.getByText(/Price edicts/)).toBeInTheDocument()
})
