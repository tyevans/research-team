import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'

import * as stories from './CoursePanes.stories.tsx'

/** The two course panes, tested through the stories that draw them.
 *
 * These render `Split` and `Pane` for real and no container at all, which is
 * the property worth pinning: `StageList` and `ArtifactList` take a `Course`
 * and callbacks, so the whole of the course page's *content* can be rendered
 * without a `QueryClientProvider`. Before the split, seeing an artifact that
 * claims nothing meant serving one.
 */
const { Course, NoArtifacts, ArtifactsClaimingNothing } = composeStories(stories)

it('draws every declared stage, run or not, with the counts on the pane head', async () => {
  render(<Course />)

  // A rail built from what happened can only show what happened; this list
  // comes from the preset. "Draft" and "Review" have not run.
  expect(await screen.findByText('Intake')).toBeInTheDocument()
  expect(screen.getByText('Draft')).toBeInTheDocument()
  expect(screen.getByText('Review')).toBeInTheDocument()
  expect(screen.getByText('1 of 4 left behind')).toBeInTheDocument()
})

/** Written-of-declared, not a percentage: a stage owing two artifacts with one
 *  written is a specific situation and "50%" is not. This also pins that a
 *  missing artifact stays in the list -- hidden, it would take with it the gap
 *  the page exists to show. */
it('keeps an unwritten artifact in the list rather than hiding it', async () => {
  render(<Course />)

  expect(await screen.findByText('objectives.md')).toBeInTheDocument()
  expect(screen.getAllByText('not written').length).toBeGreaterThan(0)
})

it('says a workflow declaring no artifacts is not a workflow missing them', async () => {
  render(<NoArtifacts />)

  expect(await screen.findByText('This workflow declares no artifacts.')).toBeInTheDocument()
  expect(screen.getByText(/Nothing here is missing/)).toBeInTheDocument()
})

/** The one artifact state the contract exists to make visible. Fails if
 *  `claims nothing` is ever folded in with "no provenance block at all": the
 *  two are different, and the difference is whether the file tried. */
it('marks an artifact that claims neither a source nor its own inference', async () => {
  render(<ArtifactsClaimingNothing />)

  expect(await screen.findByText('claims nothing')).toBeInTheDocument()
  expect(
    screen.getByText(
      'No readable frontmatter, so nothing can tell what this is or what it rests on.',
    ),
  ).toBeInTheDocument()
  expect(screen.getByText('2 unreadable')).toBeInTheDocument()
})

/** Opening a stage is the page's state rather than the list's, and only one
 *  opens at a time. Fails if `StageList` starts holding it: two rails on one
 *  page would then disagree, and the rule lives where the page is. */
it('opens one stage at a time', async () => {
  render(<Course />)

  await userEvent.click(await screen.findByRole('button', { name: /Intake/ }))
  expect(screen.getByText('spine 0')).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: /Framing/ }))
  // The first stage's detail is gone rather than joined by a second.
  expect(screen.getAllByText('spine 0')).toHaveLength(1)
  expect(screen.getByText('gate (editor):')).toBeInTheDocument()
})

/** `Split` refuses to hide the last open pane, and the course page inherits
 *  that by being one. Two columns that both fill the width have no folded-head
 *  fallback the way the research rail's strips do, so folding both would leave
 *  the page with nothing. */
it('folds a pane, and refuses to fold the last open one', async () => {
  render(<Course />)

  await userEvent.click(await screen.findByRole('button', { name: 'Collapse Stages' }))
  // Hidden rather than unmounted, which is `Pane`'s default and the right one
  // here: an opened stage survives a fold. The research rail asks for the
  // opposite (`unmountWhenCollapsed`) because a virtualizer behind a fold
  // caches a zero-height scroller, and neither list here has one. `hidden`
  // takes it out of the accessibility tree as well as off the screen.
  expect(screen.getByText('Draft')).not.toBeVisible()

  await userEvent.click(screen.getByRole('button', { name: 'Collapse Artifacts' }))
  // Refused: the artifacts pane is still open and still says so.
  expect(screen.getByRole('button', { name: 'Collapse Artifacts' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Expand Stages' })).toBeInTheDocument()
})
