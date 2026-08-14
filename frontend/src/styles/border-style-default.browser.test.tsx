import { render } from '@testing-library/react'
import { expect, it } from 'vitest'

/** That a directional border width alone draws, with no `border-solid`.
 *
 * **This test has not been run, and was not proved red.** A benchmark held the
 * machine when it was written, and the browser suite is a minute of headless
 * Chromium. It is committed unrun deliberately, because the claim it stands for
 * has just been used to withdraw `BACKLOG.md` B55 and to rewrite `CLAUDE.md`'s
 * single-side-border rule, and an unrun test that says so is more honest than a
 * paragraph of prose that cannot fail. **If it fails, the reading in that commit
 * is wrong and B55 should be reinstated.** Run it with
 * `cd frontend && npm run test:browser`.
 *
 * **What it is standing proof of.** This build imports no Tailwind preflight
 * (`theme.css:26`, deliberately), so `CLAUDE.md` carried a rule that a
 * directional width without `border-solid` draws nothing at all — every side's
 * `border-style` still the UA's `none`. Read off the built `index.css`, that is
 * false: Tailwind v4 emits the style longhand *with* the width
 * (`.border-b{border-bottom-style:var(--tw-border-style);border-bottom-width:1px}`)
 * and registers `@property --tw-border-style` with `initial-value:solid`, and
 * `border-style:none` occurs zero times in the sheet.
 *
 * **Why it cannot be a jsdom test.** jsdom applies no stylesheet, so
 * `getComputedStyle(el).borderBottomStyle` returns whatever an inline style said
 * — `''` here — whether the rule exists, does not exist, or exists and loses.
 * The two states this file separates are indistinguishable there. That is the
 * same reason `spacing-zero.browser.test.tsx` and `hidden-attribute.browser.test.tsx`
 * live beside it.
 *
 * **Why `check-tailwind.mjs` does not make it redundant.** That check asks
 * whether a selector for a class name exists in the built sheet.
 * `.border-b` exists under either reading — under the old one it would emit a
 * width and no style, and the check would be just as green. It guards the
 * declaration; this guards the outcome.
 *
 * **What each case would fail on.** The first fails if a future Tailwind stops
 * registering `--tw-border-style`, or if this build ever adds a preflight-style
 * `border-style: none` reset — which is precisely the world `CLAUDE.md` used to
 * describe. The second is the twin that makes the first mean something: an
 * element with no border utility at all must have no bottom border, or the first
 * assertion could pass on inheritance rather than on the utility.
 *
 * The third is the *other* half of the rule, the half that is real and that no
 * live call site currently violates: `border-solid` is the four-side shorthand,
 * so pairing it with one directional width and no `border-0` leaves the other
 * three sides styled with no explicit width and the UA's `medium` fills in. It
 * is asserted here rather than only described so that the surviving half of the
 * rule has a measurement too, and so that a reader who finds this file after the
 * withdrawal does not conclude the whole entry was folklore.
 */

it('draws a solid bottom border from a directional width alone', () => {
  const { container } = render(
    <>
      {/* The exact class list `BACKLOG.md` B55 listed as a defect:
          `Drawer.tsx:163` and `DecisionBar.tsx:44` both write this shape. */}
      <div data-testid="directional" className="border-b border-line" />
      <div data-testid="bare" />
    </>,
  )

  const at = (id: string) => container.querySelector(`[data-testid="${id}"]`)!

  expect(getComputedStyle(at('directional')).borderBottomStyle).toBe('solid')
  expect(getComputedStyle(at('directional')).borderBottomWidth).toBe('1px')

  // Without the twin, the assertions above could hold for a reason that has
  // nothing to do with `border-b`.
  expect(getComputedStyle(at('bare')).borderBottomStyle).toBe('none')
})

it('gives three unwanted sides a width when `border-solid` has no `border-0`', () => {
  // The half of the rule that is real. `medium` is the UA fallback and computes
  // to 3px in Chromium; asserted as a number rather than the keyword because
  // `getComputedStyle` resolves it, and recorded here so a Chromium release that
  // changes it fails this test rather than quietly making `CLAUDE.md` wrong.
  const { container } = render(
    <div data-testid="box" className="border-t border-solid border-line" />,
  )

  const style = getComputedStyle(container.querySelector('[data-testid="box"]')!)

  expect(style.borderTopWidth).toBe('1px')
  expect(style.borderLeftStyle).toBe('solid')
  expect(style.borderLeftWidth).not.toBe('0px')
})
