/** The page as a pure function of props -- no container, no repository, no
 *  store. Everything here was unreachable while `AskView` built its own store:
 *  a test wanting a failed turn *and* a banner had to make the repository
 *  reject at the right moment to get one.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import { AskPage } from './AskPage.tsx'
import { PROJECT, turn } from './ask-fixtures.ts'

const base = {
  projectId: PROJECT,
  transcript: [],
  asking: false,
  error: null,
  onAsk: () => {},
  onReset: () => {},
}

/** Two entries, not the three this asserted before increment C merged the
 *  course and research pages into one. `Course` and `Research` were two names
 *  for two routes; both now resolve to the project page, so offering both was
 *  offering one destination twice under names the console no longer uses. */
it('marks Ask as the current facet and the project as elsewhere', () => {
  render(<AskPage {...base} />)

  expect(screen.getByRole('link', { name: 'Ask' })).toHaveAttribute('aria-current', 'page')
  expect(screen.getByRole('link', { name: 'Project' })).not.toHaveAttribute('aria-current')
  expect(screen.queryByRole('link', { name: 'Course' })).toBeNull()
  expect(screen.queryByRole('link', { name: 'Research' })).toBeNull()
})

it('asks for a new chat without knowing what one is', async () => {
  const onReset = vi.fn()
  render(<AskPage {...base} onReset={onReset} />)

  await userEvent.click(screen.getByRole('button', { name: /new chat/i }))

  expect(onReset).toHaveBeenCalledTimes(1)
})

it('says a refusal twice, in two different places', () => {
  // The banner is what a reader who has scrolled away sees; the turn's copy is
  // what says which question died. Asserting both is the point -- a page-wide
  // text search would pass with either one deleted.
  render(
    <AskPage
      {...base}
      error="the model is already answering another question on this chat"
      transcript={[turn({ answer: '', citations: [], error: 'already answering' })]}
    />,
  )

  expect(screen.getByRole('alert')).toHaveTextContent(/already answering/)
  expect(screen.getByText(/already answering/, { selector: 'article p' })).toBeInTheDocument()
})
