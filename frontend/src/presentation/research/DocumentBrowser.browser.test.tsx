import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import type { TextSummary } from '@domain/research/document.ts'
import { emptyExtractionQueue } from '@domain/research/extraction-queue.ts'
import { SourceId } from '@domain/shared/identifier.ts'

import { DocumentBrowser } from './DocumentBrowser.tsx'

/** Whether the document list's focus ring is on screen, which is a
 *  measurement and so cannot be asked in `DocumentBrowser.test.tsx`.
 *
 * The same shape `FileList.browser.test.tsx` was written for, found by
 * sweeping the rest of the console for it. The row is a `<button>` at
 * `w-full` and the scroller has no padding, so
 * the row's border box *is* the scroller's padding box horizontally — and the
 * global `:focus-visible` in `tokens.css` draws 2px at `outline-offset: 1px`,
 * three pixels outside it. `overflow` clips at the padding box, so those three
 * pixels are on the far side of the clip on both sides at once.
 *
 * **Proved red.** Against the stylesheet before this change, at the 1440x900
 * viewport `vite.config.ts` sets, with the scroller 340x200 and the clip
 * (padding box) at `1..339 x 1..199`:
 *
 * | Focused | Ring | Verdict |
 * |---|---|---|
 * | first row | `-2..342 x -2..55` | left, right and top outside the clip |
 * | a middle row | `-2..342 x 136..193` | left and right outside the clip |
 * | the scroller itself | `-3..343 x -3..203` | wholly outside its own border box |
 *
 * The first row is the one a reader meets, and it keeps only its bottom edge —
 * a 2px underline where a ring was intended. jsdom reports every one of these
 * as a rule that applied perfectly: it lays nothing out, so every rect is 0x0
 * and `getComputedStyle` returns the initial `outline: none` regardless.
 *
 * What breaks these again, said plainly so a future edit is recognisable:
 * dropping `RING_INWARD` from either the scroller or the row in
 * `DocumentBrowser.tsx`, or turning its `outline-offset-[-2px]` back to a
 * positive value.
 *
 * **Rewritten for increment C slice 3, and not re-proved red.** The rules moved
 * from `research.css` to `RING_INWARD` in `DocumentBrowser.tsx` and the two
 * selectors here moved with them — `[data-document-scroll]` for the scroller
 * and `role=button` for the rows, because the class names they used to query
 * are gone. The measurements in the table above are the original ones and were
 * taken against the stylesheet; the assertions are unchanged. No gate and no
 * suite was run locally on that slice (a benchmark had the machine), so what is
 * verified here is that the assertions still name real elements — CI is the
 * first thing to actually run them. `BACKLOG.md` B54 is the precedent for
 * recording an unverified claim rather than implying one.
 */

/** Enough rows that the scroller really scrolls. An unclipped list is not the
 *  case that shipped, and it is also not the case in which Chromium makes the
 *  scroll container itself focusable — the third test depends on both. */
const documents: readonly TextSummary[] = Array.from({ length: 24 }, (_, index) => ({
  sourceId: SourceId(`0000000${String(index).padStart(1, '0')}-1111-1111-1111-111111111111`),
  kind: 'text',
  charCount: 1200 + index,
  sha256: 'abc',
  uri: null,
  title: `A paper about topic number ${index}`,
  publishedAt: null,
  note: null,
  fetchedAt: null,
  droppedReason: null,
  extracted: false,
}))

/** The rail width the browser actually gets, and a height short enough that
 *  24 rows overflow it. A list measured with room to spare measures nothing. */
const Browser = () => (
  <div style={{ width: '340px', height: '220px', display: 'flex' }}>
    <DocumentBrowser
      documents={documents}
      total={documents.length}
      filter=""
      onFilterChange={() => {}}
      onOpen={() => {}}
      queue={emptyExtractionQueue}
      extractableCount={documents.length}
      queueSize={0}
      busy={false}
      cancelling={false}
      onExtract={() => {}}
      onExtractAll={() => {}}
      onCancelExtraction={() => {}}
      onAdd={() => {}}
    />
  </div>
)

/** The outermost edge an element's outline reaches, in viewport coordinates.
 *  An outline sits `outline-offset` beyond the border box and is
 *  `outline-width` thick, so a negative offset pulls it inside. */
const ringBox = (element: HTMLElement) => {
  const style = getComputedStyle(element)
  const reach = parseFloat(style.outlineWidth) + parseFloat(style.outlineOffset)
  const box = element.getBoundingClientRect()
  return {
    drawn: style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0,
    top: box.top - reach,
    left: box.left - reach,
    right: box.right + reach,
    bottom: box.bottom + reach,
  }
}

/** What `overflow` actually clips: the padding box, not the border box. */
const clipBox = (element: HTMLElement) => {
  const box = element.getBoundingClientRect()
  return {
    top: box.top + element.clientTop,
    left: box.left + element.clientLeft,
    right: box.left + element.clientLeft + element.clientWidth,
    bottom: box.top + element.clientTop + element.clientHeight,
  }
}

const mount = async () => {
  await render(<Browser />)
  const scroller = document.querySelector('[data-document-scroll]') as HTMLElement
  // `[data-document-open]` rather than the `> button` this used to say. The row
  // is two controls now -- the open button and a sibling extract action -- and
  // while the action happens to sit inside a `<span>` and so is not a direct
  // child, a selector that depended on that would silently start measuring the
  // wrong element the day the wrapper goes.
  const rows = Array.from(document.querySelectorAll<HTMLElement>('[data-document-open]'))
  // The precondition, asserted rather than assumed: with no overflow there is
  // no clip, and every assertion below would pass against the defect.
  expect(scroller.scrollHeight).toBeGreaterThan(scroller.clientHeight)
  return { scroller, rows }
}

/** Asserted rather than assumed. `:focus-visible` after a programmatic
 *  `focus()` is a heuristic; if this engine declined to match it, every rule
 *  under test would be inert while the geometry assertions still passed. */
const focus = (element: HTMLElement) => {
  element.focus()
  expect(element.matches(':focus-visible')).toBe(true)
}

it('keeps the first document row from losing three sides of its focus ring', async () => {
  const { scroller, rows } = await mount()
  const row = rows[0]!
  focus(row)

  const ring = ringBox(row)
  const clip = clipBox(scroller)
  expect(ring.drawn).toBe(true)
  expect(ring.left).toBeGreaterThanOrEqual(clip.left)
  expect(ring.right).toBeLessThanOrEqual(clip.right)
  expect(ring.top).toBeGreaterThanOrEqual(clip.top)
  expect(ring.bottom).toBeLessThanOrEqual(clip.bottom)
})

it('keeps a row further down the list from losing its sides', async () => {
  const { scroller, rows } = await mount()
  // Not the first row: the first is clipped on three sides and would pass a
  // test that only looked at the vertical edges. This one isolates the pair
  // that is wrong for *every* row in the list, wherever it is scrolled to.
  const row = rows[3]!
  focus(row)

  const ring = ringBox(row)
  const clip = clipBox(scroller)
  expect(ring.left).toBeGreaterThanOrEqual(clip.left)
  expect(ring.right).toBeLessThanOrEqual(clip.right)
})

it('keeps the extract action’s ring inside the scroller too', async () => {
  // The row grew a second control at its right edge, which is the edge the
  // scroller clips hardest -- the open button used to be `w-full` and owned it.
  // A control that sat outside `RING_INWARD` here would lose its ring on the
  // right for every row in the list, which is the defect the three tests above
  // were written about, one element over.
  //
  // **Proved red on 2026-08-14**, and measured rather than reasoned: replacing
  // the action's `pr-3` with `pr-0 -mr-[4px]` — the smallest edit that puts the
  // button flush against the clip — gave `right = 234.33` against a clip right
  // of `227`. The margin the padding buys is what this pins; the button carries
  // the global outward `:focus-visible` (offset +1px, 2px wide) rather than
  // `RING_INWARD`, so it reaches 3px past its own border box and needs that
  // room.
  const { scroller } = await mount()
  const action = document.querySelectorAll<HTMLElement>('[data-document-row] .btn')[0]!
  focus(action)

  const ring = ringBox(action)
  const clip = clipBox(scroller)
  expect(ring.drawn).toBe(true)
  expect(ring.left).toBeGreaterThanOrEqual(clip.left)
  expect(ring.right).toBeLessThanOrEqual(clip.right)
})

it('gives the scroller itself a ring it can keep, because it can be focused', async () => {
  // The trap `FileList.browser.test.tsx` documents, met a second time:
  // the scroller carries no `tabIndex` and reads as an inert
  // wrapper, and Chromium focuses a scroll container anyway. It is a real tab
  // stop as soon as the corpus is longer than the pane.
  const { scroller } = await mount()
  focus(scroller)
  expect(document.activeElement).toBe(scroller)

  // Inside its own border box, which is what makes the ring proof against
  // whatever the rail around it does with `overflow`.
  const ring = ringBox(scroller)
  const box = scroller.getBoundingClientRect()
  expect(ring.drawn).toBe(true)
  expect(ring.top).toBeGreaterThanOrEqual(box.top)
  expect(ring.left).toBeGreaterThanOrEqual(box.left)
  expect(ring.right).toBeLessThanOrEqual(box.right)
  expect(ring.bottom).toBeLessThanOrEqual(box.bottom)
})

it('still opens the document it was asked to open', async () => {
  // Not geometry, and deliberately cheap: the rules under test are drawn on
  // the row a reader activates, and a ring change that quietly stopped the
  // row being a button would satisfy every measurement above.
  await mount()
  await expect
    .element(page.getByRole('button', { name: /A paper about topic number 0/ }))
    .toBeInTheDocument()
})
