import { composeStories } from '@storybook/react-vite'
import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import * as stories from './Flashcards.stories.tsx'

/** A flipped card reads as turned over, not as selected.
 *
 * `CLAUDE.md` records the decision this defends. `.btn[aria-pressed='true']`
 * gives a pressed control an accent border *and* accent text, and it is
 * "scoped to `.btn` rather than written bare" precisely because "`Flashcards`
 * puts `aria-pressed={flipped}` on a `role="button"` card, and a flipped card
 * turning accent-on-accent is a different decision from a toggle looking
 * pressed."
 *
 * That decision had no test. It is one deleted `.btn` from the selector away
 * at all times, and the failure would be silent everywhere jsdom can look:
 * the attribute is correct in both builds, only the computed colour differs.
 *
 * The assertions are a pair and a negative, in that order of importance. The
 * pair is what the stylesheet does intend -- `--line` face up, `--accent-dim`
 * turned over, so the card does change and this is not asserting inertness.
 * The negative is the claim: neither state is `--accent`, which is what a
 * leaked `.btn` rule would produce.
 *
 * Literals rather than reading the custom properties back, for
 * `Tabs.browser.test.tsx`'s stated reason: a token that changed to the wrong
 * value would otherwise agree with itself.
 *
 * **Proved red** by removing `:not(.btn-accent)`'s sibling scope -- writing
 * the rule as a bare `[aria-pressed='true']` in `shell.css`: the card's border
 * and colour both become `rgb(226, 164, 87)` and both negatives fail.
 */
const { Front, Flipped } = composeStories(stories)

const ACCENT = 'rgb(226, 164, 87)'
const ACCENT_DIM = 'rgb(122, 90, 44)'
const LINE = 'rgb(35, 42, 51)'

const cardStyle = () => {
  const card = document.body.querySelector('.flash-card')
  expect(card).not.toBeNull()
  return getComputedStyle(card!)
}

it('draws a face-up card in the ordinary line colour', async () => {
  await render(<Front />)
  const style = cardStyle()
  expect(style.borderTopColor).toBe(LINE)
  expect(style.color).not.toBe(ACCENT)
})

it('draws a turned-over card in the dim accent, not the accent', async () => {
  await render(<Flipped />)
  const style = cardStyle()

  // What the stylesheet does intend: the card changes.
  expect(style.borderTopColor).toBe(ACCENT_DIM)

  // The claim. A pressed `.btn` is accent border *and* accent text; a flipped
  // card is neither. If either of these becomes ACCENT, the scoping is gone.
  expect(style.borderTopColor).not.toBe(ACCENT)
  expect(style.color).not.toBe(ACCENT)
})
