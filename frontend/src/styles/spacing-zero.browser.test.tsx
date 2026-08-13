import { render } from '@testing-library/react'
import { expect, it } from 'vitest'

/** That `m-0` and `p-0` reach the element as zero.
 *
 * **Why this cannot be a jsdom test.** jsdom applies no stylesheet and
 * implements no user-agent one, so `getComputedStyle(pre).marginBlockStart` is
 * `''` whether the rule exists, does not exist, or exists and loses. The two
 * states this file separates are indistinguishable there, which is how the
 * defect shipped past a green suite: `theme.css` omits Tailwind's default
 * theme, so the base `--spacing` step was undefined, `calc(var(--spacing) * 0)`
 * was an invalid declaration, and `m-0` generated no rule at all. Five shipped
 * elements in the decision bar kept the user agent's margins.
 *
 * **Why it is not made redundant by `check-tailwind.mjs`.** That check reads
 * the built stylesheet and answers "does a rule exist", which is the more
 * exhaustive question — it covers every site, not the four here. It cannot
 * answer "does the rule *win*". Utilities live in `@layer utilities` and this
 * repository's own stylesheets are unlayered, so any project rule setting a
 * margin on these elements beats `m-0` outright and the check would stay green
 * while the pixels moved. That is not hypothetical: `.sub` and the `<pre>`'s
 * neighbours are unlayered rules on the same surfaces. The check guards the
 * declaration; this guards the outcome.
 *
 * **What each case would fail on.** Reverting `--spacing-0` from `theme.css`
 * fails every case below with the UA value named in its comment. Adding an
 * unlayered `pre { margin: 4px }` to any stylesheet fails only the first, which
 * is the case `check-tailwind.mjs` cannot see.
 *
 * The UA figures are measured in Chromium at this project's type scale, not
 * quoted from a spec — `<pre>` and `<p>` take `1em` of their *own* font size
 * and `<h4>` takes `1.33em`, so the same class removes a different number of
 * pixels on each. They are recorded as the second assertion in each case
 * rather than only in prose, so a Chromium release that changes them fails
 * here instead of quietly making this comment wrong.
 */

const blockMargin = (el: Element) => {
  const style = getComputedStyle(el)
  return [style.marginBlockStart, style.marginBlockEnd]
}

it('gives the decision bar the zero margin its markup asks for', () => {
  const { container } = render(
    <>
      {/* `Approvals.tsx`'s argument dump. `text-xs` is 10.5px, so the UA's
          `1em` block margin is 10.5px at each end — the largest single move in
          this change. */}
      <pre data-testid="pre" className="m-0 font-mono text-xs" />
      <pre data-testid="pre-ua" className="font-mono text-xs" />

      {/* `GateReview.tsx`'s findings heading. `1.33em` of the inherited size.
          Given text because `jsx-a11y/heading-has-content` is right that an
          empty heading is a defect, and because a margin is measurable on an
          empty box while a heading's is not the thing a reader sees. */}
      <h4 data-testid="h4" className="m-0 text-sm">
        blocking
      </h4>
      <h4 data-testid="h4-ua" className="text-sm">
        blocking
      </h4>

      {/* `Approvals.tsx`'s error line. */}
      <p data-testid="p" className="m-0 text-xs" />
      <p data-testid="p-ua" className="text-xs" />
    </>,
  )

  const at = (id: string) => container.querySelector(`[data-testid="${id}"]`)!

  for (const id of ['pre', 'h4', 'p']) {
    expect(blockMargin(at(id)), `${id} keeps a margin`).toEqual(['0px', '0px'])
    // The twin is what makes the first assertion mean something: if the UA
    // stopped putting a margin here, `m-0` would pass while doing nothing.
    expect(blockMargin(at(`${id}-ua`)), `${id} has no UA margin to remove`).not.toEqual([
      '0px',
      '0px',
    ])
  }
})

it('gives the finding lists the zero padding their markup asks for', () => {
  // `<ul>` is the one where `p-0` carries the visible weight rather than `m-0`:
  // the UA's `padding-inline-start: 40px` is what indents a list, and
  // `list-none` removes the marker without removing the indent. A findings list
  // has been sitting 40px in from the heading above it.
  const { container } = render(
    <>
      <ul data-testid="ul" className="m-0 list-none p-0" />
      <ul data-testid="ul-ua" className="list-none" />
    </>,
  )

  const at = (id: string) => container.querySelector(`[data-testid="${id}"]`)!

  expect(getComputedStyle(at('ul')).paddingInlineStart).toBe('0px')
  expect(blockMargin(at('ul'))).toEqual(['0px', '0px'])
  expect(getComputedStyle(at('ul-ua')).paddingInlineStart).not.toBe('0px')
})

it('gives the tooltip trigger the zero padding its comment already claimed', () => {
  // `Tooltip.tsx` says its four reset utilities exist because preflight is not
  // imported, so a bare `<button>` keeps the UA's border, background and
  // padding. Three of the four worked. `p-0` did not, so every tooltip trigger
  // in the console has been carrying the UA's button padding — measured at 1px
  // block and 6px inline in Chromium — inside a wrapper whose whole job is to
  // be invisible.
  const { container } = render(
    <>
      <button type="button" data-testid="trigger" className="cursor-help border-0 p-0" />
      <button type="button" data-testid="trigger-ua" />
    </>,
  )

  const at = (id: string) => container.querySelector(`[data-testid="${id}"]`)!
  const padding = (el: Element) => getComputedStyle(el).padding

  expect(padding(at('trigger'))).toBe('0px')
  expect(padding(at('trigger-ua'))).not.toBe('0px')
})
