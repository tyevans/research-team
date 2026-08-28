import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import * as stories from './TopicQueue.stories.tsx'
import { ROW_VERBS } from './TopicQueue.tsx'

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
 * the assertion below is that the full text is reachable, which is the part
 * that has to be true for the clamp to be acceptable at all. It used to be
 * reachable through `title` and the test said so approvingly; `title` is
 * reachable by a hovering mouse and by nothing else, so what it was really
 * asserting was that the clamped text was available to everyone who did not
 * need it.
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

  const chip = await screen.findByRole('button', { name: /failed/ })
  // Focus, not hover: hover is what `title` already did. The whole claim of
  // this conversion is that the reason arrives for a reader who never touches
  // a pointer, so the test reaches it the way that reader does.
  chip.focus()
  expect(
    await screen.findByText(
      'the model returned a citation for a source this project does not hold, twice in a row',
    ),
  ).toBeInTheDocument()
  expect(chip.textContent).toContain('failed')
})

it('disables only synthesis for a topic with nothing gathered, and says why', async () => {
  const user = userEvent.setup()
  const onDispatch = vi.fn()
  render(<NothingToSynthesise onDispatch={onDispatch} />)

  // `aria-disabled` rather than `disabled`, which is the whole point rather
  // than a spelling: a `disabled` button takes no focus and no pointer events,
  // so the sentence explaining why it is off could only ever be delivered by
  // something that does not need the button to be interactive -- which is what
  // `title` was, and why it reached nobody. The press still has to do nothing.
  const button = await screen.findByRole('button', { name: ROW_VERBS.understanding })
  expect(button).toHaveAttribute('aria-disabled', 'true')

  button.focus()
  expect(await screen.findByText(/Nothing gathered for this topic yet/)).toBeInTheDocument()

  await user.click(button)
  expect(onDispatch).not.toHaveBeenCalled()
})

/** The asymmetry `research` landing created, which nothing else asserts.
 *
 * `hasNothingToSynthesise` gates `understanding` because synthesising from
 * nothing produces the model's prior knowledge presented as project findings.
 * `research` is precisely the action that ends that state, so gating it on the
 * same predicate would lock the row shut on exactly the topics that most need
 * it -- and would look entirely correct, because "all three verbs go off
 * together" is the tidier-looking rule.
 *
 * **Proved red** by widening the predicate to all three verbs (`off={blocked
 * || empty}` on each `RowVerb` in `TopicQueue.tsx`): both presses below stop
 * firing and this fails on `research` first. The test above stays green
 * through that change, which is why the two are separate.
 *
 * `refine` is here for a different reason and it is worth naming: the refine
 * prompt forbids `record_finding`, so what makes ungrounded synthesis
 * dangerous does not apply to it -- see `docs/design/
 * topic-actions-on-the-row.md` §3.2a.
 */
it('leaves the two verbs that do not synthesise on, for a topic with nothing gathered', async () => {
  const user = userEvent.setup()
  const onDispatch = vi.fn()
  render(<NothingToSynthesise onDispatch={onDispatch} />)

  for (const action of ['research', 'refine'] as const) {
    const button = await screen.findByRole('button', { name: ROW_VERBS[action] })
    expect(button).toHaveAttribute('aria-disabled', 'false')
    await user.click(button)
    expect(onDispatch).toHaveBeenCalledWith(expect.any(String), action)
  }
})

/** One press, one action, and the pairing is the thing that can silently
 *  break.
 *
 * Three icons that all dispatch `understanding` typecheck, render identically,
 * and are indistinguishable from correct until somebody reads a file that was
 * written by the wrong prompt -- which is the shape `useTopicQueue`'s
 * hard-coded `action: 'understanding'` had. Parametrised over all three rather
 * than sampling one, because the case that separates a correct implementation
 * from `onDispatch(topicId, 'understanding')` in every handler is *any verb
 * other than the one that was there before*.
 *
 * **Proved red** by pointing every `RowVerb` at `'understanding'`: `research`
 * fails first.
 */
it.each(['research', 'understanding', 'refine'] as const)(
  'dispatches %s from the icon that offers it',
  async (action) => {
    const onDispatch = vi.fn()
    render(<Queue onDispatch={onDispatch} />)

    await userEvent.click((await screen.findAllByRole('button', { name: ROW_VERBS[action] }))[1]!)

    expect(onDispatch).toHaveBeenCalledWith('22222222-2222-2222-2222-222222222222', action)
  },
)

/** The label §3.2a of the design constrains, held against the one wording it
 *  forbids rather than against the wording chosen.
 *
 * `refine` cannot rewrite the question -- no tool a dispatch turn holds can --
 * so it writes `refinement.md` and a person applies it. "Refine this question"
 * over a control that produces a proposal is a label that lies about who
 * decided, and it is the label both the original ask and §3.2 use, which is
 * exactly why it is the one a future edit would drift back towards.
 *
 * Asserting the absence of two words rather than the presence of the chosen
 * sentence, deliberately: pinning the exact wording would make this a
 * change-detector that fails on every rephrasing, where the contract is only
 * that the control must not promise an edit it does not make. The tooltip is
 * asserted positively instead, because *that* is where the document is named
 * and a reader who never opens it is the reader this constraint is about.
 *
 * **Proved red** by relabelling the verb `Refine this question`.
 */
it('never offers to rewrite the question, because refine does not', async () => {
  render(<Queue />)

  const refine = (await screen.findAllByRole('button', { name: ROW_VERBS.refine }))[0]!
  expect(refine).toHaveAccessibleName(expect.not.stringMatching(/rewrite|refine this question/i))

  refine.focus()
  expect(await screen.findByText(/Writes refinement\.md/)).toBeInTheDocument()
  expect(screen.getByText(/You decide whether to apply it/)).toBeInTheDocument()
})

/** The hook the ring measurement finds the scroller by.
 *
 * jsdom can say nothing about the ring itself — no layout, no stylesheet — and
 * `topic-list-ring.browser.test.tsx` is where the geometry is asserted. What it
 * *can* do is guard the one thing that would make that file fail as a broken
 * test rather than as a caught defect: a rename that takes `data-topic-scroll`
 * off the list leaves the browser test dereferencing `null` and reporting
 * nothing about rings at all.
 *
 * **This fails with the change reverted** — the attribute did not exist before
 * this slice, because the browser test found the list by `.topic-list`. */
it('marks the list the queue scrolls, so the ring can be measured against it', async () => {
  const { container } = render(<Queue />)
  await screen.findByText('Who funded the study, and did they see it before publication?')

  const list = container.querySelector('[data-topic-scroll]')
  expect(list).not.toBeNull()
  expect(list!.tagName).toBe('UL')
  expect(list!.querySelectorAll('li').length).toBeGreaterThan(0)
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
  await userEvent.click(screen.getAllByRole('button', { name: ROW_VERBS.understanding })[1]!)

  // `Manage` is behind a `⋯` now, which #40 needed for its 34px and which also
  // fixes the thing the index above is working around: the trigger is named
  // after its row, so a reader hearing "More actions" gets told which topic
  // rather than hearing the same three words down the whole queue.
  const more = screen.getAllByRole('button', { name: /More actions/ })[1]!
  expect(more).toHaveAccessibleName(/spacing interact with sleep/)
  await userEvent.click(more)
  await userEvent.click(await screen.findByRole('menuitem', { name: 'Manage' }))

  expect(onDispatch).toHaveBeenCalledWith('22222222-2222-2222-2222-222222222222', 'understanding')
  expect(onManage).toHaveBeenCalledWith('22222222-2222-2222-2222-222222222222')
})
