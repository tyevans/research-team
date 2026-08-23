import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './Conversation.stories.tsx'

/** The transcript's stories render the states they are named for.
 *
 * **This file does not cover the `emptyDetail` rule, and an earlier draft of
 * this docstring claimed it did.** `Conversation.test.tsx` owns that rule
 * outright: it renders the component with an override, asserts the default
 * wording is absent, and was proved red against three breaks including
 * `emptyDetail` being ignored. Every assertion below about that rule would
 * pass with this file deleted, and the repository's convention is to say so
 * rather than leave it as reassurance.
 *
 * What this file is for is narrower and still worth having: **the stories are
 * the right stories.** The gallery is where the `emptyDetail` decision is
 * actually made -- a caller writing a new read-only view looks at
 * `EmptyWithAComposer` and `EmptyWithoutOne` side by side and sees that the
 * choice exists. A story that silently lost its override would show two
 * identical empty states and teach that the prop does not matter, and no
 * component test can see that, because from the component's side both stories
 * are correct calls.
 *
 * So the assertions here are about the fixtures, not the behaviour. The
 * distinction is worth keeping straight: `Conversation.test.tsx` fails when
 * the component breaks; this fails when the *page that explains the component*
 * breaks.
 *
 * **Proved red** by deleting `emptyDetail` from `EmptyWithoutOne`: the two
 * empty stories become identical and the third test fails, while
 * `Conversation.test.tsx` stays green throughout -- which is the split above,
 * demonstrated rather than asserted.
 */
const { AnExchange, EmptyWithAComposer, EmptyWithoutOne, Failed, AFailedTurn } =
  composeStories(stories)

it('renders a transcript', () => {
  render(<AnExchange />)
  expect(screen.getByText(/Which provinces did the tetrarchy/)).toBeInTheDocument()
  expect(screen.getByText(/the tetrarchy divided/)).toBeInTheDocument()
})

it('tells a reader with a composer to send the first turn', () => {
  render(<EmptyWithAComposer />)
  expect(screen.getByText(/Send the first turn below/)).toBeInTheDocument()
})

/** The half that matters, and the reason the pair exists in the gallery. */
it('keeps the read-only story’s override, so the pair stays a pair', () => {
  render(<EmptyWithoutOne />)
  expect(screen.queryByText(/Send the first turn below/)).not.toBeInTheDocument()
  expect(screen.getByText(/Nothing has been said in this session yet/)).toBeInTheDocument()
})

/** "Nothing was said" and "we could not find out what was said" are different
 *  facts a reader acts on differently, so they must not share a rendering. */
it('distinguishes a failed load from an empty transcript', () => {
  render(<Failed />)
  expect(screen.getByText(/503/)).toBeInTheDocument()
  expect(screen.queryByText(/Send the first turn below/)).not.toBeInTheDocument()
})

/** An error is not an answer.
 *
 *  Asserts the error text reaches the page. It does not assert how it is
 *  *marked* -- that is a class or a colour, and the colour needs a browser;
 *  said here so nobody reads this as covering the distinction visually. */
it('shows a failed turn’s message', () => {
  render(<AFailedTurn />)
  expect(screen.getByText(/The model returned no content/)).toBeInTheDocument()
})
