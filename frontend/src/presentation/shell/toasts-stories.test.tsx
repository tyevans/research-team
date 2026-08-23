import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'

import { useToasts } from '@application/notifications/toast-store.ts'

import * as stories from './Toasts.stories.tsx'

/** The toast stories draw toasts, and each one is separately dismissible.
 *
 * A toast is the one surface in the console a reader cannot go and look at --
 * it appears on an event and expires on a timer -- so the gallery is the only
 * place its wording and stacking get judged. That makes a story rendering
 * nothing especially expensive here: it would look exactly like the empty
 * state, which is also a story on the same page.
 *
 * **The store is global, so this file resets it.** `useToasts` is a module
 * singleton and the stories seed it in an effect. Without the cleanup below,
 * one test's toasts leak into the next and the counts are whatever the file's
 * running order happens to produce -- green, wrong, and impossible to read.
 *
 * **Proved red** by removing `useToasts.setState` from the stories' `Seeded`
 * effect: every count drops to 0 and three of the four tests fail, while
 * `draws nothing when there is nothing pending` stays green -- which is the
 * same "an empty component and a broken one look identical" split the
 * `VirtualList` work ran into, and the reason the empty case is asserted
 * separately rather than trusted.
 */
const { EveryTone, AFailure, AStack, Empty } = composeStories(stories)

afterEach(() => {
  useToasts.setState({ toasts: [], holds: 0 })
})

it('draws one toast per pending message', () => {
  render(<EveryTone />)
  expect(screen.getAllByRole('button', { name: /dismiss|close/i })).toHaveLength(3)
})

/** Every toast is separately dismissible.
 *
 *  A stack with one close button makes a reader discard a message they have
 *  not read. Asserted as a count against the toasts rather than as "a close
 *  button exists", which passes on exactly that build. */
it('gives every toast in a stack its own dismiss control', () => {
  render(<AStack />)
  expect(screen.getAllByRole('button', { name: /dismiss|close/i })).toHaveLength(5)
})

/** A failure's text reaches the page whole.
 *
 *  Not a truncation assertion -- that is geometry and needs a browser. This
 *  catches the cheaper and more likely failure: the message never being
 *  rendered at all. */
it('renders a failure’s message', () => {
  render(<AFailure />)
  expect(screen.getByText(/Could not reach the grader/)).toBeInTheDocument()
})

/** The state the console is in almost all the time. */
it('draws nothing when there is nothing pending', () => {
  render(<Empty />)
  expect(screen.queryAllByRole('button', { name: /dismiss|close/i })).toHaveLength(0)
})
