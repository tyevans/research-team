import { render } from '@testing-library/react'
import { expect, it } from 'vitest'

/** That the rest of `tokens.css`'s defaults lose to a utility, the way #313
 *  made the two form-control rules lose to one.
 *
 * **The third time this repository has met the same fact.** An unlayered normal
 * declaration beats a layered one whatever the specificity, Tailwind emits into
 * `@layer utilities`, and so an unlayered rule in `tokens.css` silently makes
 * every competing utility inert. CLAUDE.md records it for the focus ring
 * (`focus-visible:outline-offset-[-2px]`, dead, found twice independently by
 * measuring); #313 found it on `button`, `input`, `textarea` and `select`
 * (`bg-*`, `text-*` and `text-<size>`, all dead, since the rules were written).
 * This file is the sweep of what was left.
 *
 * Four rules were layered as a result. **Two of them have a case below, and
 * two do not** -- see the block in the middle of this file, which says which
 * and why, because a fix nothing measures should be labelled rather than
 * counted. Both cases here were proved red by removing the `@layer base`
 * wrapper from the rule they name, and that is the only thing they assert:
 * they say nothing about whether the defaults themselves are right, which is
 * `control-defaults.browser.test.tsx`'s half for the controls.
 *
 * Browser rather than jsdom for the reason the whole directory is: jsdom
 * applies no stylesheet, so a layered rule and an unlayered one produce the
 * same empty answer, and a test here would pass against either.
 */

const computed = (el: Element) => getComputedStyle(el)

it('lets box-content beat the universal box-sizing default', () => {
  // The widest of the four and the least obvious. `* { box-sizing: border-box }`
  // at specificity (0,0,0) still outranked every layered utility, so
  // `box-content` has never worked anywhere in this console. Nothing writes it
  // today -- which is exactly why nobody found it.
  const { container } = render(<div className="box-content" data-testid="wide" />)
  expect(computed(container.firstElementChild!).boxSizing).toBe('content-box')
})

it('lets a colour utility beat the bare-link default', () => {
  // `a { color: inherit }` is #313's defect one element over, and links are far
  // more common in this console than unclassed buttons were. A `text-accent` on
  // an `<a>` drew `--fg`.
  const { container } = render(
    <a className="text-accent" href="#x">
      link
    </a>,
  )
  const accent = computed(document.documentElement).getPropertyValue('--accent').trim()
  const fg = computed(document.documentElement).getPropertyValue('--fg').trim()
  expect(accent).not.toBe(fg)
  expect(computed(container.firstElementChild!).color).toBe(accent)
})

/** **Two of the four have no assertion here, and that is a gap rather than an
 *  omission.**
 *
 * `input::placeholder` and `::selection` were layered by exactly the argument
 * the three cases above measure, and the change to them is **unverified**.
 * `getComputedStyle(el, '::placeholder')` does not resolve the pseudo-element
 * in Chromium -- measured 2026-08-28, it returns the *element's* colour
 * (`rgb(215, 222, 231)`, which is `--fg`) whether the rule is layered or not --
 * and `getComputedStyle(el, '::selection')` returns `rgba(0, 0, 0, 0)`
 * unconditionally. So a test of either shape passes and fails for reasons that
 * have nothing to do with the layer.
 *
 * Written down rather than left as two missing cases, because "no test" and "a
 * test that cannot see its subject" look identical from the file listing, and
 * this repository has been bitten by the second. What would actually measure
 * them is a screenshot diff or a real text selection driven through the
 * browser, neither of which this suite has today.
 *
 * The two rules are layered anyway. The alternative is leaving two known
 * instances of a defect in place because the sweep that found them cannot also
 * prove the fix, which is the worse of the two.
 */

it('keeps the focus ring unlayered, which is the one exception', () => {
  // Not a default but a *decision*: the console has one focus ring and a
  // component does not get to opt out of it with a utility. So this asserts the
  // opposite of the four above -- the utility loses -- and it is what makes
  // `.lay-ring-inward` in `layout.css` necessary rather than redundant.
  //
  // It fails if somebody "finishes the job" by wrapping `:focus-visible` in
  // `@layer base` too, at which point every inward-ring measurement in the
  // repository is testing a rule that no longer has to exist.
  const { container } = render(
    <button type="button" className="focus-visible:outline-offset-[-2px]">
      press
    </button>,
  )
  const button = container.firstElementChild as HTMLButtonElement
  button.focus()
  expect(computed(button).outlineOffset).toBe('1px')
})
