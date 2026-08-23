import { composeStories } from '@storybook/react-vite'
import { render, screen, within } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './Timeline.stories.tsx'

/** The grid stays a grid, and cancellation stays distinct from failure.
 *
 * **The first is a defect this file is the guard for.** `role="grid"` may only
 * contain rows, and a failed turn's discarded content used to render as a bare
 * sibling of the event row -- inside the grid, without a role. It shipped that
 * way because a timeline only grows one when a turn has failed *with
 * provisional content*, which no test and no story had ever rendered. axe's
 * `aria-required-children` named it the moment a story did.
 *
 * jsdom can hold this one: it is roles and counts, not geometry. What jsdom
 * cannot hold is the axe sweep that found it, which is why both exist.
 *
 * **Proved red** by unwrapping the detail row -- rendering `<Discarded/>`
 * directly again: the first test drops from 10 rows to 9 and fails, because
 * the block is no longer a row. The row-numbering test fails with it, which is
 * the point of numbering them from the grid rather than from the array offset.
 *
 * The second pair is the domain rule. `kindOf` checks `isCancellation` before
 * classifying, so a cancelled turn does not read as a failure -- somebody
 * stopping a run and a run falling over are different events. Asserted as a
 * pair over two rows of the *same* type, because "the cancelled row has the
 * cancelled class" passes on a build that gives every `TurnFailed` that class.
 */
const { EveryKind, DiscardedContent, CancelledAgainstFailed } = composeStories(stories)

const rows = () => document.body.querySelectorAll('[role="row"]')

it('keeps every child of the grid a row, discarded content included', () => {
  render(<DiscardedContent />)

  const grid = screen.getByRole('grid')
  // Every element child of the grid declares itself a row. This is the exact
  // shape `aria-required-children` checks, asserted where it is cheap to run.
  const strays = [...grid.children].filter((child) => child.getAttribute('role') !== 'row')
  expect(strays).toHaveLength(0)

  // Nine events, the one detail row the failed turn earns, and the HEAD marker
  // the grid renders after the log -- which is the `+ 1` in `aria-rowcount`.
  expect(rows()).toHaveLength(11)
})

/** The numbering has to survive the interleaving, which is the half that would
 *  be wrong silently. */
it('numbers rows through the detail row rather than by array offset', () => {
  render(<DiscardedContent />)
  const indices = [...rows()].map((row) => row.getAttribute('aria-rowindex'))

  // Contiguous from 1, with no repeats -- a detail row inserted without
  // renumbering would duplicate its neighbour's index.
  expect(indices).toEqual(['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11'])
})

it('gives every event kind a row, including one it has never seen', () => {
  render(<EveryKind />)
  // Nine events plus the HEAD marker.
  expect(rows()).toHaveLength(10)
  expect(screen.getByText(/something this build has never seen/)).toBeInTheDocument()
})

/** The pair. Both rows are `TurnFailed`; only one was cancelled. */
it('does not colour a cancelled turn as a failure', () => {
  const { container } = render(<CancelledAgainstFailed />)

  // `kindOf` returns 'cancelled' before classifying, so the row carries
  // `k-cancelled` and not `k-failure`.
  const cancelled = container.querySelector('.k-cancelled')
  expect(cancelled).not.toBeNull()
  expect(cancelled!.className).not.toContain('is-error')
  expect(cancelled!.className).not.toContain('k-failure')

  // The other half: the row that genuinely failed is still a failure. Without
  // this, a build that gave every `TurnFailed` the cancelled treatment passes.
  const failed = container.querySelector('.k-failure')
  expect(failed).not.toBeNull()
  expect(failed!.className).toContain('is-error')
})

/** The fork button is reachable, which is the whole reason this is a grid and
 *  not a listbox. */
it('exposes the secondary action inside a row', () => {
  render(<EveryKind />)
  const first = rows()[0]
  expect(first).toBeDefined()
  expect(within(first as HTMLElement).getByRole('button', { name: /fork/i })).toBeInTheDocument()
})
