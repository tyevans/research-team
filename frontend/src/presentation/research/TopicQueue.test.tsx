import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import * as stories from './TopicQueue.stories.tsx'

/** The queue tested through its own stories.
 *
 * `composeStories` rather than fixtures rebuilt here, and the reason is
 * specific to this component: the states worth asserting -- a clamped failure
 * chip, a filter that matches nothing, a queue that is empty for a different
 * reason -- are exactly the states the stories exist to show. Written twice
 * they drift, and the direction of drift is always the same one: the story
 * stops being the case the test covers, and the workbench quietly starts
 * lying.
 *
 * What this cannot check is anything the browser computes. The failure chip's
 * clamp is `max-width` plus `text-overflow`, and jsdom lays out nothing -- so
 * the assertion below is that the full text is reachable through `title`,
 * which is the part that has to be true for the clamp to be acceptable at all.
 */
const { Queue, Dispatched, FilteredToNothing, Empty, NothingToSynthesise } = composeStories(stories)

it('renders a row per topic, with the status spelled rather than the wire value', async () => {
  render(<Queue />)

  expect(
    await screen.findByText('Who funded the study, and did they see it before publication?'),
  ).toBeInTheDocument()
  // `not_pursuing` on the wire. The old row rendered `.replace('_', ' ')` and
  // leaned on `text-transform: capitalize` to make it presentable, which is
  // two mechanisms for one job and gave the wrong answer the day a status
  // carried two underscores -- `String.replace` with a string pattern replaces
  // only the first. `statusLabel` does it once, in the domain, with
  // `replaceAll`, and the chip is lower case in every view rather than
  // capitalised in this one.
  expect(screen.getByText('not pursuing')).toBeInTheDocument()
})

it('tells an empty queue apart from a filter that hides everything', async () => {
  const { unmount } = render(<Empty />)
  expect(await screen.findByText('No topics')).toBeInTheDocument()
  unmount()

  render(<FilteredToNothing />)
  expect(await screen.findByText('No topics match')).toBeInTheDocument()
})

/** The distinction above is the reason `counts` is a prop separate from
 *  `topics`, so it is worth one test that would fail if they were merged: with
 *  one array the component cannot tell the two states apart and would have to
 *  pick one wording for both. */
it('reports the running and queued totals in one bar rather than per row', async () => {
  render(<Dispatched />)

  expect(await screen.findByText('1 running, 2 queued')).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: 'Stop' })).toHaveLength(1)
})

it('keeps a failed dispatch on the row, with its untruncated reason reachable', async () => {
  render(<Dispatched />)

  const chip = await screen.findByTitle(
    'the model returned a citation for a source this project does not hold, twice in a row',
  )
  expect(chip.textContent).toContain('failed')
})

it('disables the one verb for a topic with nothing gathered, and says why', async () => {
  render(<NothingToSynthesise />)

  const button = await screen.findByRole('button', { name: 'Write understanding' })
  expect(button).toBeDisabled()
  expect(button).toHaveAttribute('title', 'Nothing gathered for this topic yet')
})

/** Props-only, which is the claim the whole split rests on: every test in this
 *  file renders bare, with no container, no `QueryClientProvider` and no
 *  router. If any of them ever needs a wrapper, something in `TopicQueue` has
 *  started fetching.
 *
 *  What this one adds is that the row's two verbs report the topic they belong
 *  to rather than merely firing — the bug a slot-per-row arrangement invites
 *  is every row closing over the same one. */
it('reports each row’s verbs against that row’s own topic', async () => {
  const onDispatch = vi.fn()
  const onManage = vi.fn()

  render(<Queue onDispatch={onDispatch} onManage={onManage} />)

  // The second row: blocked sorts first in the story's own data, so this is
  // deliberately not the one a bug closing over "the first topic" would hit.
  await userEvent.click(screen.getAllByRole('button', { name: 'Write understanding' })[1]!)
  await userEvent.click(screen.getAllByRole('button', { name: 'Manage' })[1]!)

  expect(onDispatch).toHaveBeenCalledWith('22222222-2222-2222-2222-222222222222')
  expect(onManage).toHaveBeenCalledWith('22222222-2222-2222-2222-222222222222')
})
