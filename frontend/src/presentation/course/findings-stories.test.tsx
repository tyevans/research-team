import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './Findings.stories.tsx'

/** The list draws for the states that are not "some findings", which is where
 *  it can be wrong without looking wrong.
 *
 * Three of them, and each is a *pair* with the ordinary case:
 *
 * - Nothing at all -> nothing rendered, not a heading over an empty region.
 *   Asserting "the heading is present when there are findings" passes on a
 *   build that always renders it.
 * - Unimplemented checks with no findings -> the list still draws. The `return
 *   null` guard is on *both* being empty, and a guard on `findings` alone
 *   would hide a real state while passing every test about findings.
 * - An unknown severity -> rendered, and with the fallback edge. Reviewer
 *   prompts author these strings, so an unrecognised one is expected rather
 *   than exceptional, and dropping the row would lose a finding silently.
 *
 * **Proved red** three ways, one per pair: returning `null` when
 * `findings.length === 0` reddens the unimplemented test alone; removing the
 * guard entirely reddens the nothing-to-report test alone; and filtering rows
 * to the five known severities reddens the unknown-severity test alone.
 *
 * The *edge colours* are not asserted here. They are `border-l-*` utilities
 * whose computed value jsdom does not resolve, and `CLAUDE.md` is explicit
 * that a colour claim has to be a browser measurement. What is asserted is
 * that the row exists and carries its label.
 */
const { EverySeverity, Unimplemented, NothingToReport, TwoFromOneCheck } = composeStories(stories)

const rows = () => document.body.querySelectorAll('li')

it('renders a row per finding, including a severity it has never seen', () => {
  render(<EverySeverity />)
  expect(rows()).toHaveLength(6)
  expect(screen.getByText(/A severity this build has never heard of/)).toBeInTheDocument()
})

/** The guard is on both lists being empty, not on `findings` alone. */
it('draws the list for unimplemented checks even with no findings', () => {
  render(<Unimplemented />)
  expect(screen.getByText(/This stage’s checks/)).toBeInTheDocument()
  expect(document.body.textContent ?? '').toContain('outline.reading_level')
})

/** The half that gives the one above its meaning. */
it('draws nothing at all when there are neither findings nor gaps', () => {
  render(<NothingToReport />)
  expect(screen.queryByText(/This stage’s checks/)).not.toBeInTheDocument()
  expect(rows()).toHaveLength(0)
})

/** The documented cost of matching on `check`: two findings from one check
 *  both mark. Asserted so the behaviour is a decision on record rather than a
 *  surprise to whoever next changes the matching. */
it('marks every finding from the check a link named', () => {
  const { container } = render(<TwoFromOneCheck />)
  expect(container.querySelectorAll('li.bg-bg-raise')).toHaveLength(2)
  expect(rows()).toHaveLength(3)
})
