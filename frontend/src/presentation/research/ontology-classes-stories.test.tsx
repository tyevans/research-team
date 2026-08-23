import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './OntologyClasses.stories.tsx'

/** The two distinctions this list exists to draw stay drawn.
 *
 * A force-directed drawing cannot show order, so this list is the only place a
 * scale, a set and a taxonomy are told apart -- and that difference is the
 * whole claim a discovery pass makes.
 *
 * Both assertions below are *pairs*, and neither half is worth having alone:
 *
 * - A set must not read as a sequence. Asserting "the scale shows positions"
 *   passes on a build that numbers everything.
 * - An incompleteness marker must be absent where no count was stated.
 *   Asserting "the incomplete class is marked" passes on a build that marks
 *   every class, which is the state `ontology.ts` explains the `complete`
 *   default was chosen to avoid.
 *
 * **Proved red** by setting `declaredCount: 4` on `NoCountStated`'s class --
 * the smallest change that makes it counted: the negative half fails on the
 * word `stated` appearing, while `Incomplete` stays green. That is the pair
 * doing its job rather than two spellings of one assertion.
 *
 * The taxonomy's *nesting* is not asserted here. `childrenOf` is domain code
 * with its own tests, and what a story could add is that the tree is not
 * duplicated -- a count of rendered names, which would break the moment a card
 * gained a second mention of its own title. Left out rather than written
 * loosely.
 */
const { AScaleAgainstASet, Incomplete, NoCountStated, NothingFound, WithRejectedMembers } =
  composeStories(stories)

it('shows both a scale and a set, as different things', () => {
  render(<AScaleAgainstASet />)
  expect(screen.getByText(/Senatorial ranks/)).toBeInTheDocument()
  expect(screen.getByText(/Tetrarchic capitals/)).toBeInTheDocument()
  // The scale's first position is named; the set's members are present and
  // carry no position of their own.
  expect(screen.getByText(/Quaestor/)).toBeInTheDocument()
  expect(screen.getByText(/Nicomedia/)).toBeInTheDocument()
})

/** The document said five and four were found: the checksum reads the
 *  shortfall, and a sentence says what it means. */
it('shows the shortfall when a class does not match the count it stated', () => {
  render(<Incomplete />)
  expect(screen.getByText('4 of 5 stated')).toBeInTheDocument()
  expect(screen.getByText(/counted more than it named/)).toBeInTheDocument()
})

/** The half that gives the shortfall its meaning.
 *
 *  An uncounted class says "4 members" and nothing else. Saying "4 of 4
 *  stated" here would look like a verification and be nothing of the kind --
 *  which is `Checksum`'s own argument, and the reason this asserts the absence
 *  of the word `stated` rather than the absence of a marker class.
 *
 *  Scoped to the rendered list rather than the container, and that is not
 *  fussiness: the first draft asserted `/incomplete/i` over the whole
 *  container and failed against the *story's own heading*, which contains the
 *  phrase "not incomplete". A test that can be reddened by prose around the
 *  component is not testing the component. */
it('does not show a shortfall for a class that stated no count', () => {
  render(<NoCountStated />)
  const list = document.body.querySelector('ul')
  expect(list).not.toBeNull()
  expect(list!.textContent ?? '').toContain('4 members')
  expect(list!.textContent ?? '').not.toContain('stated')
  expect(list!.textContent ?? '').not.toContain('counted more than it named')
})

/** Refusals are information about the pass, not something to hide. */
it('keeps a refused member and its reason', () => {
  render(<WithRejectedMembers />)
  expect(screen.getByText(/Constantine/)).toBeInTheDocument()
  expect(screen.getByText(/acclaimed after the tetrarchy had lapsed/)).toBeInTheDocument()
})

/** An empty state that names the action, rather than reporting an absence. */
it('tells a reader how to find classes when there are none', () => {
  render(<NothingFound />)
  expect(screen.getByText(/No classes found yet/)).toBeInTheDocument()
  expect(screen.getByText(/discovery pass/)).toBeInTheDocument()
})
