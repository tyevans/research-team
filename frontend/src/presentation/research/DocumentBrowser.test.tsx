import { composeStories } from '@storybook/react-vite'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import * as stories from './DocumentBrowser.stories.tsx'

const { Corpus, FilteredToNothing, Empty, Extracting } = composeStories(stories)

/** The row a document's title sits in, so a test can ask about the controls
 *  beside it rather than about whichever button the query happened to find
 *  first -- there are two per row now. */
const rowFor = (title: string) =>
  screen.getByText(title).closest<HTMLElement>('[data-document-row]')!

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

/** The row offers extraction only when pressing it would do something.
 *
 * Four states in one render, because they are exclusive and the failure this
 * pins is a row drawing two of them -- "queued" beside "extracted" is the
 * shape of that mistake. `aria-disabled` rather than `disabled` throughout, so
 * the tooltip saying *why* a control is off stays reachable by something other
 * than a mouse; that choice is what makes `toHaveAttribute` the right question
 * here rather than `toBeDisabled`.
 */
it('offers extraction only on a row that can be extracted', async () => {
  render(<Extracting />)
  await screen.findByText('Spacing effects in long-term retention, part 1')

  const running = rowFor('Spacing effects in long-term retention, part 1')
  expect(within(running).getByText('Extracting…')).toBeInTheDocument()
  expect(within(running).getByRole('button', { name: 'Extract' })).toHaveAttribute(
    'aria-disabled',
    'true',
  )

  const queued = rowFor(
    'A very long title of the kind that wraps to two lines in a 340px rail and is exactly why rows are measured rather than assumed',
  )
  expect(within(queued).getByText('Queued for extraction')).toBeInTheDocument()
  expect(within(queued).getByRole('button', { name: 'Extract' })).toHaveAttribute(
    'aria-disabled',
    'true',
  )

  const extracted = rowFor('Spacing effects in long-term retention, part 5')
  expect(within(extracted).getByText('Extracted')).toBeInTheDocument()
  expect(within(extracted).getByRole('button', { name: 'Extract' })).toHaveAttribute(
    'aria-disabled',
    'true',
  )

  // A failure is retryable, and its detail is on the row: it is the only
  // account of itself anywhere, so a row that dropped it would tell the reader
  // a document is not extracted and never why.
  const failed = rowFor('Spacing effects in long-term retention, part 4')
  expect(
    within(failed).getByText(/Extraction failed: the model refused: context length exceeded/),
  ).toBeInTheDocument()
  expect(within(failed).getByRole('button', { name: 'Retry' })).toHaveAttribute(
    'aria-disabled',
    'false',
  )

  // Untouched, so the control is live.
  const idle = rowFor('Spacing effects in long-term retention, part 6')
  expect(within(idle).getByRole('button', { name: 'Extract' })).toHaveAttribute(
    'aria-disabled',
    'false',
  )
})

/** A dropped document offers no extraction control at all, rather than an off
 *  one -- the server excludes dropped documents from extract-all, so an off
 *  button here would be a promise that pressing it might one day work.
 *
 * Stated plainly: this asserts an absence, so it passes against a build with
 * no extraction controls anywhere. What it pins is the *exclusion*, not the
 * feature; the test above it is the one that goes red without the controls. */
it('offers a dropped document no extraction at all', async () => {
  render(<Extracting />)
  await screen.findByText('Spacing effects in long-term retention, part 3')

  const dropped = rowFor('Spacing effects in long-term retention, part 3')
  expect(dropped).toHaveAttribute('data-dropped', 'true')
  expect(within(dropped).queryByRole('button', { name: /extract|retry/i })).not.toBeInTheDocument()
})

it('reports the document a reader asked to extract', async () => {
  const onExtract = vi.fn()
  render(<Extracting onExtract={onExtract} />)
  await screen.findByText('Spacing effects in long-term retention, part 6')

  await userEvent.click(
    within(rowFor('Spacing effects in long-term retention, part 6')).getByRole('button', {
      name: 'Extract',
    }),
  )

  expect(onExtract).toHaveBeenCalledWith('00000006-1111-2222-3333-444444444444')
})

/** The guard `aria-disabled` needs and `disabled` would have given for free.
 *  Keeping the button focusable is what makes "why is this off" answerable at
 *  all, and the cost is that nothing but the handler stops the click. */
it('does not queue a document that is already running', async () => {
  const onExtract = vi.fn()
  render(<Extracting onExtract={onExtract} />)
  await screen.findByText('Spacing effects in long-term retention, part 1')

  await userEvent.click(
    within(rowFor('Spacing effects in long-term retention, part 1')).getByRole('button', {
      name: 'Extract',
    }),
  )

  expect(onExtract).not.toHaveBeenCalled()
})

/** The bulk control says how many it would take on, and the stop control
 *  appears only when there is something to stop -- one per project, matching
 *  the server, where cancel is per project and a per-row stop would offer an
 *  action it cannot honour. */
it('counts what extract-all would take on, and offers a stop only when the queue holds something', async () => {
  const { unmount } = render(<Extracting />)
  expect(await screen.findByRole('button', { name: 'Extract all (29)' })).toBeInTheDocument()
  expect(screen.getByText('2 extracting or queued')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument()
  unmount()

  render(<Corpus />)
  await screen.findByRole('button', { name: 'Extract all (32)' })
  // Nothing running and nothing queued: a stop control here would stop nothing.
  expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
})

/** A search field over an empty corpus is a control with nothing to do, and so
 *  is an extract-all over one. Both are behind the same guard, which is the
 *  point: the header is one block and it goes as a block. */
it('offers no extract-all over a corpus that holds nothing', async () => {
  render(<Empty />)
  await screen.findByText('No documents')
  expect(screen.queryByRole('button', { name: /extract all/i })).not.toBeInTheDocument()
})
