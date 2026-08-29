import { render } from '@testing-library/react'
import { expect, it } from 'vitest'

import { Markdown } from '@presentation/common/content.tsx'

/** That rendered markdown is dressed at all.
 *
 * **It was not, from 2026-08-07 to 2026-08-29.** `markdown.css` styled nine
 * class families -- `.md-h`, `.md-p`, `.md-hr`, `.md-list`, `.md-li`,
 * `.md-task`, `.md-quote`, `.md-inline-code`, `.md-table` -- and `marked`
 * emits none of them. Every heading, paragraph, list, quote, table and code
 * span on every surface that renders model prose fell back to the browser's own
 * defaults, in a build that imports no Tailwind preflight. BACKLOG B158 has the
 * enumeration and the history.
 *
 * **This file drives the real renderer, and that is the whole design of it.**
 * It does not hand-write `<h2 class="md-h">` and check the rule; it renders
 * `<Markdown>` over a source string, exactly as `AskTurn`, `LessonDocument`,
 * `DocumentReader` and eight other components do, and measures what comes out.
 * The defect was precisely a gap between what a stylesheet selected and what a
 * renderer produced, and a fixture that writes the markup itself supplies the
 * agreement it is supposed to be testing -- which is CLAUDE.md's fixture rule
 * exactly, one layer over. Swap the renderer again, or add a `marked` option
 * that changes an element, and this goes red; nothing that reads a class name
 * would.
 *
 * **Browser rather than jsdom, and it has to be.** jsdom applies no stylesheet,
 * so `getComputedStyle` returns what an inline style said and nothing a rule
 * contributed: a selector that matches nothing and one that matches every
 * element are the same empty answer there. The one existing browser assertion
 * anywhere near this (`mention-snippet.browser.test.tsx`, `marginBottom` on a
 * `.md-bare` last child) read `'0px'` and was satisfied *because* the rule was
 * dead. That is the shape this file exists to make impossible.
 *
 * Each case asserts a value the stylesheet names rather than "not the default",
 * so it fails on a missing rule and on a rule that changed by accident. What it
 * does not assert is that the values are the right ones -- they are carried
 * across from the dead rules unchanged, deliberately, so the diff is about
 * selectors meeting elements.
 */

const SOURCE = [
  '# Title',
  '',
  '## Section',
  '',
  '### Sub',
  '',
  'A paragraph with `inline code` in it.',
  '',
  '- first',
  '- second',
  '',
  '> A quotation.',
  '',
  '| a | b |',
  '| --- | --- |',
  '| 1 | 2 |',
  '',
  '```',
  'fenced',
  '```',
  '',
  '---',
].join('\n')

const doc = () => {
  const { container } = render(<Markdown source={SOURCE} />)
  const md = container.querySelector('.md')
  expect(md).not.toBeNull()
  return md!
}

/** Every element the assertions below reach for, asserted present in one place.
 *
 * `querySelector` returning `null` and a rule not applying are different
 * failures with the same feel, and the second is the one this file is about. If
 * `marked` stops emitting a `<blockquote>` the case for blockquotes should say
 * so, not report an undefined style. */
const one = (root: Element, selector: string) => {
  const found = root.querySelector(selector)
  expect(found, `the renderer emitted no ${selector}`).not.toBeNull()
  return getComputedStyle(found!)
}

const token = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim()

it('gives every rendered heading the shared heading rule', () => {
  const md = doc()
  // `margin: 16px 0 6px`, and a browser's own `<h2>` margin is em-relative and
  // symmetric -- so this fails with the rule absent rather than coinciding
  // with it.
  const h2 = one(md, 'h2')
  expect(h2.marginTop).toBe('16px')
  expect(h2.marginBottom).toBe('6px')
  expect(h2.fontWeight).toBe('600')
})

it('rules off the first two heading levels and not the third', () => {
  const md = doc()
  // The one visual difference between `h1`/`h2` and `h3` in this stylesheet,
  // and the reason `.md h3` is a separate rule rather than a font size on the
  // shared one.
  expect(one(md, 'h1').borderBottomWidth).toBe('1px')
  expect(one(md, 'h2').borderBottomWidth).toBe('1px')
  expect(one(md, 'h3, h4, h5, h6').borderBottomWidth ?? '0px').toBe('0px')
})

it('drops a heading flush against the top of the block', () => {
  const md = doc()
  // `.md > :is(h1..h6):first-child`. Written as `.md > .md-h:first-child`
  // before, which selected nothing, so every document opened with 16px of
  // space above its title.
  expect(one(md, 'h1').marginTop).toBe('0px')
})

it('gives a paragraph its rhythm', () => {
  expect(one(doc(), 'p').marginBottom).toBe('10px')
})

it('indents a list rather than leaving it on the browser default', () => {
  const md = doc()
  // 22px, against Chromium's own 40px. A value assertion rather than an
  // inequality: both were "some indent", and the point is which stylesheet is
  // deciding.
  expect(one(md, 'ul').paddingLeft).toBe('22px')
  expect(one(md, 'ul').marginBottom).toBe('10px')
})

it('draws the quote rule down the left of a blockquote', () => {
  const md = doc()
  const quote = one(md, 'blockquote')
  expect(quote.borderLeftWidth).toBe('2px')
  expect(quote.borderLeftStyle).toBe('solid')
  // A browser's `<blockquote>` has a 40px left *margin* and no border at all,
  // which is what this was drawing.
  expect(quote.paddingLeft).toBe('12px')
  expect(quote.color).toBe(token('--fg-dim'))
})

it('sets inline code apart without touching a fenced block', () => {
  const md = doc()
  const raised = token('--bg-raise')
  // `:not(pre) > code`. With the `:not(pre)` dropped, the second assertion
  // fails: the `<code>` inside the `<pre>` draws its own background and its own
  // padding inside the block's.
  expect(one(md, 'p > code').backgroundColor).toBe(raised)
  expect(one(md, 'pre > code').backgroundColor).toBe('rgba(0, 0, 0, 0)')
})

it('dresses a fenced block as a block', () => {
  const md = doc()
  const pre = one(md, 'pre')
  expect(pre.backgroundColor).toBe(token('--bg-raise'))
  expect(pre.overflowX).toBe('auto')
  expect(pre.paddingTop).toBe('8px')
})

it('collapses the borders of a table and draws them on the cells', () => {
  const md = doc()
  expect(one(md, 'table').borderCollapse).toBe('collapse')
  const cell = one(md, 'td')
  expect(cell.borderTopWidth).toBe('1px')
  expect(cell.paddingLeft).toBe('8px')
  expect(one(md, 'th').color).toBe(token('--fg-dim'))
})

it('draws a horizontal rule as one line rather than as a groove', () => {
  const md = doc()
  const hr = one(md, 'hr')
  // A browser's own `<hr>` is an inset border on all four sides. The rule zeroes
  // it and puts a line on the top edge only -- which is `border: 0` followed by
  // `border-top`, both halves of the fix CLAUDE.md's border entry describes.
  expect(hr.borderTopWidth).toBe('1px')
  expect(hr.borderBottomWidth).toBe('0px')
  expect(hr.borderTopStyle).toBe('solid')
})

it('leaves a component-authored `<pre class="md-code">` dressed the same way', () => {
  // The one selector in the layered block that is a class rather than an
  // element. `LessonDocument` builds two `<pre class="md-code">` blocks itself
  // (an unrecognised fence, and a component that did not parse) and
  // `components.css` selects on the class, so it is kept -- but it must dress
  // identically to a `<pre>` the renderer produced, or the two failure states
  // of a lesson document look like different features.
  const { container } = render(
    <div className="md">
      <pre className="md-code">
        <code>raw</code>
      </pre>
    </div>,
  )
  expect(getComputedStyle(container.querySelector('pre')!).backgroundColor).toBe(
    token('--bg-raise'),
  )
})
