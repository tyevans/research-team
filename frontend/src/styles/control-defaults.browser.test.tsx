import { render } from '@testing-library/react'
import { expect, it } from 'vitest'

/** A utility written on a form control has to actually win.
 *
 * `tokens.css` gives every bare `button`, `input`, `textarea` and `select` a
 * background, a colour and `font: inherit`, so an unclassed control is legible
 * on this theme. Those are *defaults*, and defaults have to lose to anything a
 * component says about a particular control.
 *
 * They did not. Written unlayered, the element selector at (0,0,1) beat every
 * Tailwind utility at (0,1,0), because **layer order is consulted before
 * specificity and an unlayered normal declaration wins against a layered
 * one.** Tailwind emits into `@layer utilities`. So `bg-transparent`,
 * `text-accent`, `text-xs` and `font-mono` on a `<button>` were all inert —
 * every one of them present in the class attribute, present in the bundle, and
 * never meeting.
 *
 * `font: inherit` is the one that reaches furthest, because it is a
 * *shorthand*: it sets `font-size` too, so the size utilities went with the
 * colour ones.
 *
 * How it surfaced, on 2026-08-28: `CourseCard` stretches its click target as
 * `<button class="absolute inset-0 … bg-[transparent]">` over the whole card,
 * so the inert background painted `--bg` opaquely across the card's art, title
 * and blurb. Every catalog card rendered as an empty bordered box.
 * `elementFromPoint` at a title's centre returned the button.
 *
 * **This suite is the only one that can hold it.** jsdom applies no stylesheet
 * and returns only what an inline style said, so there the class is in the
 * attribute, the rule is in the bundle, and the assertion cannot be made at
 * all. It is the same reason the inward focus ring needed a measurement, and
 * this is the third time this repository has paid for the unlayered-rule trap.
 *
 * What each case fails on: unwrap the matching rule in `tokens.css` from its
 * `@layer base` and the assertion goes red with the default's own value —
 * `rgb(11, 13, 16)` for the background, `rgb(215, 222, 231)` for the colour.
 * Proved that way before being trusted.
 */

const computed = (el: Element) => getComputedStyle(el)

it('lets a background utility beat the bare-control default', () => {
  const { getByTestId } = render(
    <button type="button" data-testid="control" className="bg-transparent">
      press
    </button>,
  )

  // `rgba(0, 0, 0, 0)` is how a browser reports `transparent`. The default this
  // has to beat is `--bg`, an opaque near-black, which is why the card it was
  // painted over vanished rather than merely changing tone.
  expect(computed(getByTestId('control')).backgroundColor).toBe('rgba(0, 0, 0, 0)')
})

it('lets a colour utility beat the bare-control default', () => {
  const { getByTestId } = render(
    <button type="button" data-testid="control" className="text-accent">
      press
    </button>,
  )

  const accent = computed(document.documentElement).getPropertyValue('--accent').trim()
  // Compared against the token rather than a literal, so a palette change does
  // not make this test wrong about what it is testing. What matters is that it
  // is *not* `--fg`, which is what `color: inherit` was giving it.
  const fg = computed(document.documentElement).getPropertyValue('--fg').trim()
  expect(accent).not.toBe(fg)

  const drawn = computed(getByTestId('control')).color
  expect(drawn).not.toBe(hexToRgb(fg))
  expect(drawn).toBe(hexToRgb(accent))
})

it('lets a size utility beat `font: inherit`, which is a shorthand', () => {
  // The subtle half. `font: inherit` sets `font-size`, so this was inert for
  // the same reason the colour was -- and nothing about `text-xs` suggests it
  // is competing with a `font` shorthand.
  const { getByTestId } = render(
    <>
      <button type="button" data-testid="small" className="text-xs">
        press
      </button>
      <button type="button" data-testid="plain">
        press
      </button>
    </>,
  )

  const small = parseFloat(computed(getByTestId('small')).fontSize)
  const plain = parseFloat(computed(getByTestId('plain')).fontSize)
  expect(small).toBeLessThan(plain)
})

it('still dresses a control that says nothing', () => {
  // The half that must not regress. Layering the defaults makes them lose to
  // utilities; it must not make them lose to nothing at all, or a bare
  // `<button>` goes back to the UA's buttonface at about 1.15:1 against this
  // theme's text -- the measurement `tokens.css` records for it.
  const { getByTestId } = render(
    <button type="button" data-testid="plain">
      press
    </button>,
  )

  const bg = computed(document.documentElement).getPropertyValue('--bg').trim()
  expect(computed(getByTestId('plain')).backgroundColor).toBe(hexToRgb(bg))
})

/** `getPropertyValue` hands back the token as authored (`#0b0d10`);
 *  `getComputedStyle().color` reports `rgb(...)`. One of the two has to be
 *  converted, and converting the token keeps the assertion reading in the
 *  units the browser actually reports. */
const hexToRgb = (hex: string): string => {
  const value = hex.replace('#', '')
  const full =
    value.length === 3
      ? value
          .split('')
          .map((c) => c + c)
          .join('')
      : value
  const n = parseInt(full, 16)
  return `rgb(${String((n >> 16) & 255)}, ${String((n >> 8) & 255)}, ${String(n & 255)})`
}
