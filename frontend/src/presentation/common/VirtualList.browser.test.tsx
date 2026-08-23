import { composeStories } from '@storybook/react-vite'
import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import * as stories from './VirtualList.stories.tsx'

/** A virtualized list that draws nothing looks exactly like one that works.
 *
 * `VirtualList.tsx` records the defect: the scroller belongs to the caller, a
 * parent's ref attaches after its children's, so reading it at render returned
 * `null` on the only render that mattered and `getVirtualItems()` came back
 * empty **forever** — nothing re-rendered afterwards, so it never asked again.
 * The symptom was a correctly sized `<ul>` containing no rows.
 *
 * That is the failure this file exists to make loud, and it is why the
 * `VirtualList` stories cannot be trusted on sight: a story reproducing the
 * bug renders a plausible empty pane and certifies nothing.
 *
 * **Why this is a browser test and not a jsdom one.** `vitest.setup.ts` pins
 * `offsetWidth`/`offsetHeight` to constants and jsdom reports every element
 * height as 0. The component's `|| estimate` fallback exists for that reason,
 * and its effect is that in jsdom every row *is* its estimate — which is the
 * one condition under which the three defects the stories are about cannot
 * occur. A jsdom version of this file would pass against a broken component.
 *
 * **Proved red** on 2026-08-23 by changing `Scroller` in the stories to pass a
 * ref never attached to any element — the exact shape of the original defect.
 * Result: three of the four fail with `expected 0 to be greater than 0`, and
 * the stories still *render* a bordered box of the right size with nothing in
 * it. So these measure drawing rather than mounting.
 *
 * The fourth stayed green, and that is the finding rather than a gap. "Draws
 * nothing" is correct for an empty list and is also the whole symptom of the
 * defect, so the empty-list case cannot tell them apart and no assertion can
 * make it. It is kept because it fixes the meaning of the other three: they
 * are about *rows*, not about the component rendering at all. Anyone tempted
 * to reduce this file to one "it renders" test should read that pair of
 * results first.
 */
const { Plain, BelowAHeader, RaggedRows, Empty } = composeStories(stories)

/** Queried from the document rather than from a render result.
 *
 *  `vitest-browser-react`'s `render` is async and returns a locator API with no
 *  `container`, and these assertions are about geometry on real laid-out
 *  elements — so the document is the honest scope. Auto-cleanup between tests
 *  is what keeps one story's rows out of the next one's count; the empty-list
 *  test at the bottom fails loudly if that ever stops being true. */
const drawnRows = () => document.body.querySelectorAll('li[data-index]')

/** Rows are drawn at all, and virtualized rather than all present.
 *
 *  Both halves matter. `> 0` catches the empty-forever defect; `< 200` catches
 *  a build where virtualization has silently stopped and the list is rendering
 *  every row, which performs badly and passes any test that only counts up. */
it('draws a window of rows rather than none of them or all of them', async () => {
  await render(<Plain />)
  await expect.poll(() => drawnRows().length).toBeGreaterThan(0)
  expect(drawnRows().length).toBeLessThan(200)
})

/** The `scrollMargin` case: a list that does not start at its scroller's top.
 *
 *  Asserts the *first drawn row is the first row*. Without the margin the
 *  window is displaced by the header's height, so at rest the list opens part
 *  way down — which is the visible form of the bug and is what a reader meets
 *  before they scroll at all. */
it('opens on the first row even when a header sits above the list', async () => {
  await render(<BelowAHeader />)
  await expect.poll(() => drawnRows().length).toBeGreaterThan(0)
  expect(drawnRows()[0]?.getAttribute('data-index')).toBe('0')
})

/** The per-row measurement case: rows that wrap must not overlap.
 *
 *  Measured as a geometry assertion rather than a height one, because the
 *  estimate being wrong is only a defect when it makes rows collide. Each
 *  row's top must be at or below the previous row's bottom. A build trusting
 *  the 34px estimate against a wrapped row draws the next one over it and
 *  fails here by roughly a line's height. */
it('never draws a ragged row over the row beneath it', async () => {
  await render(<RaggedRows />)
  await expect.poll(() => drawnRows().length).toBeGreaterThan(2)

  const boxes = [...drawnRows()].map((row) => row.getBoundingClientRect())
  boxes.sort((a, b) => a.top - b.top)

  const overlaps = boxes.filter((box, i) => i > 0 && box.top < (boxes[i - 1]?.bottom ?? 0) - 0.5)
  expect(overlaps).toHaveLength(0)

  // The anti-rubber-stamp half: rows of genuinely different heights were
  // present, so the assertion above was exercised rather than vacuously true
  // against a uniform list.
  const heights = new Set(boxes.map((box) => Math.round(box.height)))
  expect(heights.size).toBeGreaterThan(1)
})

/** An empty list draws no rows and reserves no scroll.
 *
 *  This is the one case where "nothing drawn" is correct, and it is here so
 *  that the assertions above are read as being about *rows*, not about the
 *  component rendering at all. */
it('draws nothing for an empty list', async () => {
  await render(<Empty />)
  expect(drawnRows()).toHaveLength(0)
})
