import { composeStories } from '@storybook/react-vite'
import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import * as stories from './Conversation.stories.tsx'

/** The live tail reads as one list with the transcript, and still says it is
 *  live.
 *
 * Both halves of that sentence are computed style and layout, which is to say
 * both are invisible to the jsdom suite. `Conversation.test.tsx` can assert
 * that a live bubble is a child of `.conv` — a DOM fact — and can assert
 * nothing at all about whether it *looks* like it belongs there or whether the
 * thing marking it as provisional survived the move. In jsdom
 * `getComputedStyle` returns only what an inline style said, so every
 * assertion below would read `''` and pass against a stylesheet that was
 * never loaded.
 *
 * The arrangement this replaced is the reason it is worth measuring. Until
 * 2026-08-28 the tail was a sibling component in a `.activity` box with
 * `max-height: 50%` and `overflow-y: auto` — a second scroller inside the
 * pane, which is what trapped a long stream's overflow off the bottom while
 * the pane itself had room. That box is gone; a nested scroller reappearing
 * is the specific regression the last test here is for.
 */
const { ATurnInFlight } = composeStories(stories)

/** Throws rather than returning `null`, which is the difference between a
 *  failure that names the selector and one that says "parameter 1 is not of
 *  type 'Element'" twelve frames into `getComputedStyle`.
 *
 * The third test needs it for a second reason: it counts elements matching a
 * property, and an empty document satisfies that count perfectly. Written
 * against `document.body` with an unawaited `render` it passed while the other
 * three failed, which is the exact shape of a test that cannot fail. */
/** A colour token as the engine reports it on an element, so a `--accent` of
 *  `oklch(...)` or `#abc` can be compared with a `borderLeftColor` of
 *  `rgb(...)`. */
const resolve = (colour: string): string => {
  const probe = document.createElement('span')
  probe.style.color = colour
  document.body.append(probe)
  const value = getComputedStyle(probe).color
  probe.remove()
  return value
}

const find = (selector: string): HTMLElement => {
  const element = document.body.querySelector<HTMLElement>(selector)
  if (!element) throw new Error(`nothing matched ${selector}`)
  return element
}

it('draws a live entry on the same frame as a recorded one', async () => {
  await render(<ATurnInFlight />)

  const a = getComputedStyle(find('.conv .msg'))
  const b = getComputedStyle(find('.conv .provisional'))

  // One rhythm down the column. The old tray differed on all three — its own
  // background, no border, and 0.7 opacity — which is what made it read as a
  // separate surface rather than as the end of this one.
  expect(b.backgroundColor).toBe(a.backgroundColor)
  expect(b.borderTopWidth).toBe(a.borderTopWidth)
  expect(b.opacity).toBe('1')
})

it('still marks it as not yet recorded, in the one place they differ', async () => {
  await render(<ATurnInFlight />)

  // `:not(.provisional-tool)` deliberately. The story's first live entry is a
  // tool call, whose rail is `--k-tool` — and `--k-tool` and `--accent` are
  // *the same colour* in both themes today (`theme.css:204,252`). Against that
  // bubble the accent assertion below passes whatever the prose rule says, and
  // it did: the tray-styling revert left this test green until the selector
  // was narrowed.
  const a = getComputedStyle(find('.conv .msg'))
  const b = getComputedStyle(find('.conv .provisional:not(.provisional-tool)'))

  // The whole of the differentiation: a thicker rail, in the accent colour
  // specifically. Named against the resolved token rather than merely asserted
  // to differ from `.msg`'s border — the tray this replaced *also* had a rail
  // that differed from it (2px of `--fg-faint`), so "not the same as the
  // message's" is a claim the old stylesheet satisfied too and cannot separate
  // the two.
  const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()
  expect(accent).not.toBe('')
  expect(b.borderLeftColor).toBe(resolve(accent))
  expect(b.borderLeftColor).not.toBe(a.borderLeftColor)
  expect(parseFloat(b.borderLeftWidth)).toBeGreaterThan(parseFloat(a.borderLeftWidth))

  // And the dot, which is the part that says *still arriving* rather than
  // merely *not recorded* — a stalled turn and a streaming one otherwise look
  // identical. Both halves: a box with width, and a `content` that actually
  // generates it. Width alone is reported for a `::before` with `content:
  // none`, which is a rule that draws nothing.
  const dot = getComputedStyle(
    find('.conv .provisional:not(.provisional-tool) .provisional-tag'),
    '::before',
  )
  expect(dot.content).not.toBe('none')
  expect(parseFloat(dot.width)).toBeGreaterThan(0)
})

it('leaves the transcript with exactly one scroller', async () => {
  await render(<ATurnInFlight />)

  // Asserted first, because the filter below is satisfied by an empty document
  // just as well as by a correct one.
  const scroll = find('.conv-scroll')
  expect(scroll.querySelectorAll('.provisional').length).toBeGreaterThan(0)

  const scrollers = [...scroll.querySelectorAll<HTMLElement>('*')].filter((element) => {
    const overflow = getComputedStyle(element).overflowY
    return overflow === 'auto' || overflow === 'scroll'
  })

  // Nothing inside `.conv-scroll` scrolls on its own. A box scrolling inside a
  // box is reachable only by dragging its bar — the outer one absorbs the
  // wheel — and the inner one here held the content a reader is most likely to
  // be watching arrive.
  //
  // A guard against the arrangement coming back rather than a reproduction of
  // it: reverting the stylesheet alone leaves this green, because `.activity`
  // is not in the tree any more and its `overflow-y` matches nothing. **Proved
  // red** by putting `overflow-y: auto` on `.provisional` instead, which is
  // the form the regression would take now.
  expect(scrollers).toHaveLength(0)
})

it('renders streamed markdown as markup, not as its source', async () => {
  await render(<ATurnInFlight />)

  // The jsdom suite asserts the same thing and this is not redundant with it:
  // there it is `<h2>` in a tree, here it is that the heading is *bigger than
  // the paragraph under it*. Markdown rendered into a container the
  // stylesheet does not dress is markup nobody can see the point of, which is
  // a way for this to be half-done and look done.
  const heading = find('.provisional-body h2')
  const paragraph = find('.provisional-body p')

  expect(parseFloat(getComputedStyle(heading).fontSize)).toBeGreaterThan(
    parseFloat(getComputedStyle(paragraph).fontSize),
  )
})
