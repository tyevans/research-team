import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import * as stories from './SeedForm.stories.tsx'

const { Fresh, Ready, Running, RunningFromAnotherTab, FailedLastRun } = composeStories(stories)

it('refuses a subject that is only whitespace', async () => {
  render(<Fresh subject="   " />)

  // Trimmed before the check, not just before the request. The same rule
  // `TopicManagePane`'s justification enforces, for the identical reason.
  expect(screen.getByRole('button', { name: 'Seed topics' })).toBeDisabled()
})

it('submits the subject it was given', async () => {
  const onSubmit = vi.fn()
  render(<Ready onSubmit={onSubmit} />)

  await userEvent.click(screen.getByRole('button', { name: 'Seed topics' }))

  expect(onSubmit).toHaveBeenCalledOnce()
})

/** The running frame the server mints carries no subject — it exists before
 *  the model call that would name one — so the panel names the run from what
 *  *this tab* asked for, and says less when it did not ask. Fails if the two
 *  cases are collapsed: a tab that picked up another tab's run would start
 *  claiming a subject it has no way to know. */
it('names a run this tab started, and does not invent one it did not', async () => {
  const { unmount } = render(<Running />)
  expect(screen.getByRole('status').textContent).toContain(
    'spaced repetition and memory consolidation',
  )
  unmount()

  render(<RunningFromAnotherTab />)
  expect(screen.getByRole('status')).toHaveTextContent('Naming topics…')
})

it('keeps a failed run on screen with its reason', async () => {
  render(<FailedLastRun />)

  // A panel that cleared itself is how a failed seed came to look exactly like
  // a hung one.
  expect(
    screen.getByText('The last seed failed: the model returned no topics for that subject'),
  ).toBeInTheDocument()
  // And the form is usable again, which is the other half of the same point.
  expect(screen.getByLabelText('Subject')).toBeEnabled()
})

it('locks the box while a run is in flight', async () => {
  render(<Running />)

  expect(screen.getByLabelText('Subject')).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Seeding…' })).toBeDisabled()
})
