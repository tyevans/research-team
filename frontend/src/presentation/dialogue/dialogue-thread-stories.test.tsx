import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './DialogueThread.stories.tsx'

/** The thread stories draw a dialogue, and the outstanding marker follows
 *  whether anything is outstanding.
 *
 * The companion the `VirtualList` work argued for. A thread maps over turns,
 * so an empty or mis-shaped transcript renders a valid, plausible page and the
 * axe sweep has no opinion about it.
 *
 * The pair worth having is `Outstanding` against `Concluded`. They are the
 * same transcript, and a build that keyed `.dlg-pending` off "last turn"
 * rather than off "anything outstanding" draws them identically -- telling a
 * reader they are being waited on when the conversation is over. Each
 * assertion alone passes on such a build; only the pair fails.
 *
 * **This is not new coverage of that rule and should not be read as such.**
 * `DialoguePage.browser.test.tsx` already has `stops glowing at the last
 * question once the dialogue has concluded`, and it is the better test: it
 * compares the two computed `border-left-color`s against each other, which is
 * the actual glow. It also lives in the `browser` project, which `CLAUDE.md`
 * states is deliberately outside CI.
 *
 * So the split is deliberate. That test measures the paint and nothing runs
 * it; this one asserts the class and runs on every push. A build where
 * `.dlg-pending` is applied correctly and *styled* wrongly passes here and
 * fails there -- which is the right way round, because the class is the part a
 * refactor moves and the colour is the part a stylesheet edit moves.
 *
 * jsdom, because every claim here is text or class membership. jsdom reads
 * both those border colours as the empty string, which is why the real
 * assertion cannot live here.
 *
 * **Proved red** by dropping the `concluded` guard from both `outstanding`
 * props in `DialogueThread.tsx`: the second test fails with the marker still
 * on the last exchange.
 */
const { Outstanding, Concluded, JustOpened, PartialTranscript } = composeStories(stories)

const pending = () => document.body.querySelectorAll('.dlg-pending')

it('marks the newest question as outstanding while the dialogue is running', () => {
  render(<Outstanding />)
  expect(pending().length).toBeGreaterThan(0)
})

/** The half that matters. */
it('marks nothing as outstanding once the dialogue has concluded', () => {
  render(<Concluded />)
  expect(pending()).toHaveLength(0)
})

/** The opening lives on the row, not on a turn.
 *
 *  So a thread with an empty transcript is not an empty page. A build that
 *  rendered the opening from `transcript[0]` draws nothing here and passes
 *  every other test in this file. */
it('shows the opening question with no turns at all', () => {
  render(<JustOpened />)
  expect(screen.getByText(/Did it\?/)).toBeInTheDocument()
})

/** A transcript that does not start at turn 0 still renders both its turns.
 *
 *  This does not catch the `position`-versus-index defect on its own -- that
 *  needs stored progress to mis-attribute, which these stories deliberately
 *  do not carry. What it fixes is that the *case* exists in the gallery at
 *  all, so the next person changing the keying has a page it is visible on.
 *  Said plainly rather than implied, because a test named after a hazard it
 *  cannot detect is worse than no test. */
it('renders a transcript that starts part way through', () => {
  render(<PartialTranscript />)
  expect(screen.getByText(/Constantine/)).toBeInTheDocument()
  expect(screen.getByText(/what the creed was for/)).toBeInTheDocument()
})
