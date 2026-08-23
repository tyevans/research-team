import { composeStories } from '@storybook/react-vite'
import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import * as stories from './Mcq.stories.tsx'

/** A lesson's buttons still take a visible focus ring after losing their own
 *  rule.
 *
 * Merging `CmpButton` into `Button` deleted six rules from `components.css`,
 * and one of them was a `:focus-visible` declaration these buttons shared with
 * `.flash-card`, `.cloze-input` and `.cmp input`. The reasoning for removing
 * it was that `tokens.css`'s global `:focus-visible` covers every focusable
 * element, so the local copy was redundant.
 *
 * That reasoning is correct and it is exactly the shape of reasoning
 * `CLAUDE.md` records going wrong twice. The inward focus ring shipped broken
 * for a whole slice because three working stylesheet rules were moved onto a
 * utility constant and reported as "carried across unchanged" -- an unlayered
 * rule beats a layered one, so the utility was inert, and the class was in the
 * attribute while the computed value disagreed. A deleted rule and a
 * substituted one fail the same way: silently, with a green suite.
 *
 * So this measures rather than reasons. **Measured on 2026-08-23** in
 * Chromium: `2px solid rgb(226, 164, 87)`, which is `--accent`.
 *
 * The button under test is the accent one, deliberately. `.btn-accent` fills
 * with `--accent` and the ring is drawn in `--accent` too, so if any button
 * were going to lose its ring to its own background it is this one. Taken from
 * `Answered` rather than `Correct` because a submitted question disables the
 * submit button, and a disabled element takes no focus -- an earlier version
 * of this probe read `3px none` off exactly that and briefly looked like a
 * finding.
 *
 * **Proved red** by deleting the global `:focus-visible` block from
 * `tokens.css`: `expected 'auto' to be 'solid'`. The rule it defends is two
 * files away from the component, which is the argument for the test existing.
 *
 * `auto`, not `none`, and the difference is the honest reading of what this
 * test is for. Removing the house rule does not make focus invisible -- the
 * UA draws its own ring, and `color-scheme: dark` at the top of `tokens.css`
 * means that ring is even a reasonable colour. So this is not an
 * accessibility backstop; a build that failed it would still be operable from
 * a keyboard. What it defends is that the console's focus treatment is *the
 * console's*, one accent at one width across every control, rather than
 * whatever each browser decided. That is worth a test precisely because the
 * failure would look fine in Chromium and different in Firefox, and nobody
 * would file it.
 */
const { Answered } = composeStories(stories)

const ACCENT = 'rgb(226, 164, 87)'

it('gives a lesson’s accent button the global focus ring', async () => {
  await render(<Answered />)

  const submit = [...document.body.querySelectorAll('button')].find((button) =>
    /check answer/i.test(button.textContent ?? ''),
  )
  expect(submit).toBeDefined()
  expect(submit!.disabled).toBe(false)

  submit!.focus()
  expect(document.activeElement).toBe(submit)

  const style = getComputedStyle(submit!)
  expect(style.outlineStyle).toBe('solid')
  expect(style.outlineWidth).toBe('2px')
  expect(style.outlineColor).toBe(ACCENT)
})
