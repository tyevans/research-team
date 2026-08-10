import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import * as stories from './DocumentBrowser.stories.tsx'

const { Corpus, FilteredToNothing, Empty } = composeStories(stories)

it('draws the corpus, keeping a dropped source in the list with its reason', async () => {
  render(<Corpus />)

  expect(
    await screen.findByText('Spacing effects in long-term retention, part 1'),
  ).toBeInTheDocument()
  // Dropped sources are an audit trail: hiding them would misreport what the
  // project holds, so the row stays and carries the reason.
  expect(
    screen.getByText('Dropped: paywalled: only the abstract was reachable'),
  ).toBeInTheDocument()
})

/** The state the old component could not reach, and the reason it is worth a
 *  test rather than only a story: `DocumentList` returned early on an empty
 *  *fetch*, so a corpus with sources in it and a filter matching none of them
 *  rendered an empty `<ul>` and no explanation at all. Fails if the two empty
 *  states are collapsed back into one. */
it('tells an empty corpus apart from a filter that matches nothing', async () => {
  const { unmount } = render(<Empty />)
  expect(await screen.findByText('No documents')).toBeInTheDocument()
  // No filter box over an empty corpus: a search field with nothing to search.
  expect(screen.queryByLabelText('Filter documents')).not.toBeInTheDocument()
  unmount()

  render(<FilteredToNothing />)
  expect(await screen.findByText('No documents match')).toBeInTheDocument()
  expect(screen.getByLabelText('Filter documents')).toHaveValue('thermodynamics')
})

it('reports the source a reader opened, and holds no opinion about what happens next', async () => {
  const onOpen = vi.fn()
  render(<Corpus onOpen={onOpen} />)

  // Located by its title rather than by an accessible name: the name is the
  // title run together with the char count, and a regex over it also matches
  // parts 10 through 19.
  const title = await screen.findByText('Spacing effects in long-term retention, part 1')
  await userEvent.click(title.closest('button')!)

  expect(onOpen).toHaveBeenCalledWith('00000001-1111-2222-3333-444444444444')
})
