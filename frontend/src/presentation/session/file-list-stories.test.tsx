import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './FileList.stories.tsx'

/** The listbox is one tab stop, and the two empty states are two facts.
 *
 * **The first is the claim a linter argues with.** This is an
 * `aria-activedescendant` listbox: the container carries `tabIndex={0}` and
 * the arrow handler, each `option` is deliberately *not* focusable, and
 * selection is announced by the container pointing at a row's id. The file
 * carries a disable comment saying so, because `jsx-a11y` models only the
 * other allowed pattern (roving tabindex) and would have every file in the tab
 * order.
 *
 * A disable comment is an assertion nobody checks, which is what this replaces.
 * Asserted as a pair -- one focusable element, and `aria-activedescendant`
 * actually resolving -- because either alone permits the other to be wrong: a
 * listbox with no tab stop at all also has "no focusable options", and a
 * container pointing at a missing id also "has an activedescendant".
 *
 * **Proved red** two ways. Giving each option `tabIndex={0}` fails the first
 * alone. Dropping `aria-activedescendant` fails the second alone.
 *
 * The `historicalAt` pair is the domain rule: an empty workspace means
 * something different depending on where the reader is standing, and a build
 * that gave both one sentence would tell a reader scrubbed into the past that
 * the agent has written nothing -- false the moment they scrub forward.
 */
const { AWorkspace, OneOpen, EmptyLive, EmptyHistorical, NoRevisions } = composeStories(stories)

const focusable = (root: HTMLElement) =>
  root.querySelectorAll('[tabindex]:not([tabindex="-1"]), button, a[href], input')

it('is a single tab stop, not one per file', () => {
  const { container } = render(<AWorkspace />)
  const stops = focusable(container)
  expect(stops).toHaveLength(1)
  expect(stops[0]).toBe(screen.getByRole('listbox'))
})

/** The other half: the pointer has to resolve to a real option. */
it('points aria-activedescendant at the open file', () => {
  render(<OneOpen />)
  const listbox = screen.getByRole('listbox')
  const id = listbox.getAttribute('aria-activedescendant')
  expect(id).toBeTruthy()

  const active = document.getElementById(id!)
  expect(active).not.toBeNull()
  expect(active!.getAttribute('role')).toBe('option')
  expect(active!.getAttribute('aria-selected')).toBe('true')
  expect(active!.textContent).toContain('notes/tetrarchy.md')
})

/** Nothing open, nothing pointed at -- rather than a pointer at a row that is
 *  not selected, which would announce a selection the page does not have. */
it('points at nothing when no file is open', () => {
  render(<AWorkspace />)
  expect(screen.getByRole('listbox').getAttribute('aria-activedescendant')).toBeNull()
})

/** The pair. Same absence, different fact. */
it('says the agent has written nothing while following the head', () => {
  render(<EmptyLive />)
  expect(screen.getByText(/has not written anything yet/)).toBeInTheDocument()
})

it('says the workspace was empty at that event when scrubbed', () => {
  render(<EmptyHistorical />)
  expect(screen.getByText(/was empty at event 40/)).toBeInTheDocument()
  expect(screen.queryByText(/has not written anything yet/)).not.toBeInTheDocument()
})

/** A file never edited shows no revision marker rather than `r0`. */
it('omits the revision marker for a file that has never been edited', () => {
  const { container } = render(<NoRevisions />)
  expect(container.textContent ?? '').not.toMatch(/\br0\b/)
})
