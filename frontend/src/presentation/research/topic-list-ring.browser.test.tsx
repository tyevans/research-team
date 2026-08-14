import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import { focusCounts, type TopicView } from '@domain/research/topic.ts'
import { TopicId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { TopicQueue } from './TopicQueue.tsx'

/** Whether the topic queue's focus ring is on screen — the second of the two
 *  live exposures `component-system-spec.md` §5.2 names, and the last one.
 *
 * The shape is the one `FileList.browser.test.tsx` was written for and
 * `DocumentBrowser.browser.test.tsx` met again: a scroll container with
 * `padding: 0` and `overflow-y: auto`, wearing the global `:focus-visible` from
 * `tokens.css` — 2px at `outline-offset: 1px`, so three pixels *outside* the
 * border box. `overflow` clips at the padding box, and with no padding the
 * padding box and the border box are the same rectangle, so the whole ring is
 * on the far side of the clip. Chromium makes a scroll container focusable with
 * no `tabIndex` at all, so this is a real tab stop the moment the queue is
 * longer than the rail.
 *
 * **Proved red**, twice, and the second one is the finding. Measured at the
 * 1440x900 viewport `vite.config.ts` sets, list 340 wide, clip (padding box)
 * `0..340 x 75.5..300.5`:
 *
 * | State of `RING_INWARD` | Ring reaches | Verdict |
 * | --- | --- | --- |
 * | absent (what shipped) | `-3..343 x 72.5..303` | outside the clip on all four sides; nothing visible |
 * | present, no `!` | `-3..343 x 72.5..303` | **identical** — the utility loses to an unlayered rule |
 * | present, with `!` | `0..340 x 75.5..300` | flush with the border box, wholly inside the clip |
 * | `.lay-ring-inward` | `0..340 x 75.5..300` | **the same numbers**, re-measured 2026-08-14 |
 *
 * The middle row is why this file exists rather than merely restating
 * `DocumentBrowser.browser.test.tsx`: `tokens.css:339` is an unlayered
 * `:focus-visible` and Tailwind's utilities live in `@layer utilities`, so the
 * class was present, the rule was generated, and the offset was still `+1px`.
 * Reasoning alone gets the first row and stops.
 *
 * The ring is *drawn* in every row above — `outline-style` is `solid`
 * throughout — so the defect is purely one of position. That is why every
 * assertion here is geometry and none is presence alone.
 *
 * **The fix that shipped is the last row, not the third.** Two spellings of it
 * existed for a day -- a trailing `!` here and `.lay-ring-inward` in the graph
 * and the document browser -- and the class won: this codebase uses `!`
 * nowhere, a forgotten one fails silently and identically, and a named rule
 * gives the measurement somewhere to live. The geometry is unchanged between
 * the two, which is the point of keeping the third row above.
 *
 * What breaks these again, said plainly so a future edit is recognisable:
 * dropping `RING_INWARD` from the list in `TopicQueue.tsx`, respelling it as
 * `focus-visible:outline-offset-*` utilities (which is the third row, and is
 * inert), turning `.lay-ring-inward`'s offset positive, or giving the list
 * padding without revisiting the offset.
 *
 * jsdom can judge none of it. It lays nothing out, so every rect is 0x0;
 * it applies no stylesheet, so `getComputedStyle` answers the initial
 * `outline: none` whatever matched; and `scrollHeight` is 0 everywhere, so even
 * the precondition below is unaskable there. Every assertion in this file would
 * pass in `TopicQueue.test.tsx` against the defect.
 */

/** Enough topics that the list really scrolls. An unclipped list is not the
 *  case that shipped, and it is also not the case in which Chromium makes the
 *  container itself focusable — both tests depend on both. */
const topics: readonly TopicView[] = Array.from({ length: 24 }, (_, index) => ({
  topicId: TopicId(`0000000${String(index).padStart(1, '0')}-1111-1111-1111-111111111111`),
  question: `Question number ${index}, long enough to wrap the way a real one does`,
  status: 'investigating' as const,
  sources: 4,
  findings: 2,
  openSubQuestions: 0,
  triggers: [],
  needsAttention: false,
  isBlocked: false,
}))

/** The rail width the queue actually gets, and a height short enough that 24
 *  rows overflow it. A queue measured with room to spare measures nothing. */
const Rail = () => (
  <OverlayHost>
    <div style={{ width: '340px', height: '300px', display: 'flex', flexDirection: 'column' }}>
      <TopicQueue
        topics={topics}
        counts={focusCounts(topics)}
        focus="all"
        search=""
        dispatches={new Map()}
        running={false}
        queuedCount={0}
        dispatching={false}
        stopping={false}
        onFocusChange={() => {}}
        onSearchChange={() => {}}
        onDispatch={() => {}}
        onManage={() => {}}
        onStop={() => {}}
      />
    </div>
  </OverlayHost>
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
  await render(<Rail />)
  const list = document.querySelector('[data-topic-scroll]') as HTMLElement
  // The precondition, asserted rather than assumed: with no overflow there is
  // no clip, and every assertion below would pass against the defect.
  expect(list.scrollHeight).toBeGreaterThan(list.clientHeight)
  return list
}

/** Asserted rather than assumed. `:focus-visible` after a programmatic
 *  `focus()` is a heuristic; if this engine declined to match it, the rule
 *  under test would be inert while the geometry assertions still passed. */
const focus = (element: HTMLElement) => {
  element.focus()
  expect(element.matches(':focus-visible')).toBe(true)
}

it('keeps the topic list from scrolling its own focus ring out of sight', async () => {
  const list = await mount()
  focus(list)
  expect(document.activeElement).toBe(list)

  const ring = ringBox(list)
  const clip = clipBox(list)
  expect(ring.drawn).toBe(true)
  expect(ring.top).toBeGreaterThanOrEqual(clip.top)
  expect(ring.left).toBeGreaterThanOrEqual(clip.left)
  expect(ring.right).toBeLessThanOrEqual(clip.right)
  expect(ring.bottom).toBeLessThanOrEqual(clip.bottom)
})

it('keeps the ring inside whatever the rail around it does with overflow', async () => {
  // The other half, and not the same assertion: the test above says the list
  // does not clip its own ring, this one says no ancestor can either, which is
  // what a negative offset buys and a `overflow: visible` parent would hide.
  const list = await mount()
  focus(list)

  const ring = ringBox(list)
  const box = list.getBoundingClientRect()
  expect(ring.top).toBeGreaterThanOrEqual(box.top)
  expect(ring.left).toBeGreaterThanOrEqual(box.left)
  expect(ring.right).toBeLessThanOrEqual(box.right)
  expect(ring.bottom).toBeLessThanOrEqual(box.bottom)
})

it('still renders the rows it was given', async () => {
  // Not geometry, and deliberately cheap: a ring change that quietly stopped
  // the list rendering rows would satisfy every measurement above, because an
  // empty `<ul>` in a 300px column scrolls nothing and would fail the
  // precondition rather than the assertions — which is a failure that reads as
  // a broken test rather than a broken component.
  const list = await mount()
  expect(list.querySelectorAll('li').length).toBe(topics.length)
})
