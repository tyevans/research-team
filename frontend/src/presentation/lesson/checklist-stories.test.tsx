import { composeStories } from '@storybook/react-vite'
import { render, screen, within } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './Checklist.stories.tsx'

/** A checklist only promises to keep ticks where they can be kept.
 *
 * Whether a tick survives is two facts: `persist` on the block is the author's
 * request, `AttemptsApi.saveChecklist` is the surface's capability, and
 * `use-attempts.ts` leaves the latter `undefined` rather than a no-op so the
 * widget can tell them apart.
 *
 * **The widget was reading only the first, and that was a live defect.** A
 * checklist authored with `persist: true` inside an ask answer or a dialogue
 * question -- both of which render `LessonDocument` with no `saveChecklist` --
 * drew "saved as you go" and saved nothing. The tick landed, the label
 * reassured, and the reader found out on their next visit.
 *
 * **Proved red** against the previous line, `checklist.persist ? …`: the
 * second test fails, because the unsaveable surface renders the promise.
 *
 * The assertions are a pair on purpose. A build that dropped the hint
 * altogether passes the negative half on its own, and that build is also
 * wrong -- a lesson that does keep ticks should say so.
 *
 * Scoped with `within` rather than `screen`, because both halves of
 * `PersistsAgainstCannot` are on one page and the whole point is that they
 * differ. That is also the lesson two earlier files in this series learnt the
 * hard way: a story is a page, and its own prose is queryable text.
 */
const { PersistsAgainstCannot, NotPersisted, RequiredOutstanding, SaveFailed } =
  composeStories(stories)

const sections = () => [...document.body.querySelectorAll('section')]

it('promises to keep ticks on a surface that can keep them', () => {
  render(<PersistsAgainstCannot />)
  const lesson = sections()[0]
  expect(lesson).toBeDefined()
  expect(within(lesson!).getByText(/saved as you go/)).toBeInTheDocument()
})

/** The half that is the defect. */
it('makes no such promise where there is nothing to save into', () => {
  render(<PersistsAgainstCannot />)
  const ask = sections()[1]
  expect(ask).toBeDefined()
  expect(within(ask!).queryByText(/saved as you go/)).not.toBeInTheDocument()
})

/** An author who did not ask for persistence is not told about it either. */
it('says nothing about saving when the block did not ask for it', () => {
  render(<NotPersisted />)
  expect(screen.queryByText(/saved as you go/)).not.toBeInTheDocument()
})

/** A failed save replaces the reassurance rather than joining it: "saved as
 *  you go" is exactly the claim that turned out to be false. */
it('replaces the promise with the failure rather than showing both', () => {
  render(<SaveFailed />)
  expect(screen.getByText(/not saved: the workspace is read-only/)).toBeInTheDocument()
  expect(screen.queryByText(/saved as you go/)).not.toBeInTheDocument()
})

/** Required items are tallied separately, so "6 of 8" cannot hide that every
 *  required item is outstanding. */
it('counts required items separately from the total', () => {
  render(<RequiredOutstanding />)
  expect(screen.getByText(/6 of 8 done/)).toBeInTheDocument()
  expect(screen.getByText(/0\/2 required/)).toBeInTheDocument()
})
