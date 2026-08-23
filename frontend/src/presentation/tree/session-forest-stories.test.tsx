import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './SessionForest.stories.tsx'

/** The forest stories render rows, and the rows say what they are for.
 *
 * The companion the `VirtualList` work argued for: the axe sweep globs stories
 * and catches one that throws, but a story rendering an empty `<ul>` passes
 * it. A forest is exactly that shape of component -- it maps over nodes, so
 * an empty or mis-shaped fixture draws a valid, empty, plausible list.
 *
 * jsdom, because every claim below is text or a role.
 *
 * **Proved red** by making the fixture's `node` helper drop its children --
 * which is the realistic defect rather than an empty list, because a
 * recursion that stops at depth 1 draws a perfectly reasonable flat list and
 * nothing about it looks wrong. Two tests fail: `expected 4 but got 1`, and
 * the fork chip disappears with the generation that carried it.

 * Worth noting which three stayed green. The row count, the empty-title
 * wording and the held marker are all about a *single* row, so a forest that
 * had stopped nesting entirely would still pass them. That is the split this
 * file is arranged around: three tests about what a row says, two about the
 * structure it sits in, and only the second pair can see the recursion.
 */
const { EveryRowState, Lineage, Held } = composeStories(stories)

const rows = () => document.body.querySelectorAll('button.row')

it('draws a row per session', () => {
  render(<EveryRowState />)
  expect(rows()).toHaveLength(5)
})

/** A session with nothing said in it says so.
 *
 *  The rule is that a row is readable on its own. An empty title renders as
 *  blank space, which reads as a loading row rather than as an idle session. */
it('names a session with no messages rather than drawing an empty title', () => {
  render(<EveryRowState />)
  expect(screen.getByText('no messages yet')).toBeInTheDocument()
})

/** The whole reason the nesting survives here.
 *
 *  Four sessions across three generations. Asserts the count rather than the
 *  indentation, which is geometry and belongs in a browser: what this catches
 *  is a recursion that stops at depth 1, which draws a perfectly reasonable
 *  flat list of one. */
it('renders every generation of a fork chain, not just the first', () => {
  render(<Lineage />)
  expect(rows()).toHaveLength(4)
})

/** The fork chip carries the divergence point into the trail. */
it('says where a fork diverged, on the row', () => {
  render(<Lineage />)
  expect(screen.getAllByText(/forked @ 42/).length).toBeGreaterThan(0)
  expect(screen.getByText(/forked @ 61/)).toBeInTheDocument()
})

/** `held` is a prop rather than a field, so exactly one row can carry it and
 *  the story has to be the thing that says which. */
it('marks exactly one row as held', () => {
  render(<Held />)
  expect(screen.getAllByText('held')).toHaveLength(1)
})

/** The fixture ids are distinguishable in the eight characters the row shows.
 *
 *  `SessionRow` renders `shortId`, which is the first eight. The first draft
 *  of the stories gave every session the same prefix, so the gallery drew five
 *  rows above one repeated id and taught that the column carries nothing. Real
 *  ids are random and do not collide there; a fixture that makes a working
 *  column look useless is worse than no fixture.
 *
 *  Caught by screenshotting the story, not by any assertion -- which is the
 *  argument for this one existing. */
it('gives every row a distinguishable short id', () => {
  render(<EveryRowState />)
  const shown = [...document.body.querySelectorAll('.row-id')].map((each) => each.textContent)
  expect(new Set(shown).size).toBe(shown.length)
  expect(shown).toHaveLength(5)
})
