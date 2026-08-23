import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import { PROJECT_ROW_HEIGHT } from './ProjectRows.tsx'
import { SkeletonRows } from './Skeletons.tsx'

/** The placeholder is the size of the row it stands in for, and nothing was
 *  checking that.
 *
 * `Skeletons.tsx` states the claim and its reason in one breath:
 *
 * > Not `loading projects…`. Every log frame invalidates this page's queries,
 * > so a text line that appears and vanishes where content is about to land is
 * > the thing that makes a live page feel unstable — the layout jumps on a
 * > refetch that changed nothing. **A block of the right size does not move
 * > when it is replaced.**
 *
 * That is falsifiable, and it was false. `.skeleton-row` was `height: 84px` in
 * `tree.css` while `ProjectRows` estimated the row it replaces at
 * `PROJECT_ROW_HEIGHT = 108`. Two numbers for one fact, in two files, in two
 * languages, neither citing the other — and `ProjectList` draws four
 * skeletons, so a page settling moved about 96px every time it went pending.
 *
 * **Measured in Chromium on 2026-08-23**, composing `ProjectCard`'s stories one
 * per test so cleanup applies between them:
 *
 * | | height |
 * |---|---|
 * | `.skeleton-row` (before) | 84 |
 * | `PROJECT_ROW_HEIGHT` estimate | 108 |
 * | `ProjectCard` — `Bare` | 67 |
 * | `ProjectCard` — `AsTheLandingPageDrawsIt` | 147 |
 * | `ProjectCard` — `Expanded` | 167 |
 *
 * The skeleton matched none of them. It is 108 now, which is the estimate
 * rather than any of the card measurements, and the choice is stated in
 * `tree.css`: the landing page's rows are closed until a reader opens one, 147
 * is an open card with its preview, and 108 is what the code already believed a
 * closed row to be. Agreeing with the existing belief beats introducing a fifth
 * number.
 *
 * **What this test is not.** It compares a CSS height to a TypeScript constant.
 * It does not measure a real `ProjectListRow`, which needs a query client and a
 * rollup, and it would not catch the estimate itself being wrong — if a row
 * grows and `PROJECT_ROW_HEIGHT` is not updated, this stays green and both
 * numbers are wrong together. That is a real limit and the reason it is worth
 * writing down: what this defends is the two numbers *agreeing*, which is the
 * thing that silently stopped being true.
 *
 * **Why a browser test.** jsdom applies no stylesheet and `vitest.setup.ts`
 * pins the offset dimensions to constants, so `.skeleton-row`'s height there is
 * whatever the harness decided and never what `tree.css` says.
 *
 * **Proved red** by setting the height back to `84px`: fails with
 * `expected 84 to be 108`.
 */
it('draws a placeholder the height the row is estimated to be', async () => {
  await render(<SkeletonRows count={1} />)

  const skeleton = document.body.querySelector('.skeleton-row')
  expect(skeleton).not.toBeNull()

  expect(Math.round(skeleton!.getBoundingClientRect().height)).toBe(PROJECT_ROW_HEIGHT)
})

/** The placeholder draws at all, which the assertion above cannot tell from a
 *  stylesheet that failed to load.
 *
 *  A missing `tree.css` gives `.skeleton-row` a height of 0, and 0 is not 108,
 *  so the test above would fail rather than pass by luck. This one is here for
 *  the opposite direction: it fixes what `count` means, so a `SkeletonRows`
 *  that silently rendered nothing is caught by something other than the eye. */
it('draws one placeholder per requested row', async () => {
  await render(<SkeletonRows count={4} />)
  expect(document.body.querySelectorAll('.skeleton-row')).toHaveLength(4)
})
