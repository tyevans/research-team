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
  expect(drawn).not.toBe(fg)
  expect(drawn).toBe(accent)
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
  expect(computed(getByTestId('plain')).backgroundColor).toBe(bg)
})

/** **`hexToRgb` used to live here and is deleted, which is a fact about the
 *  palette rather than about this test.**
 *
 * It converted `#e2a457` to `rgb(226, 164, 87)`, because `getPropertyValue`
 * handed back the token exactly as authored while `getComputedStyle().color`
 * reports `rgb(...)`. That is true of an *unregistered* custom property and is
 * no longer true of these: the light-mode commit declares every colour alias
 * with `@property { syntax: "<color>" }`, and a registered property computes to
 * a resolved colour -- so `getPropertyValue('--accent')` now returns
 * `rgb(226, 164, 87)` itself and the helper was converting a string that was
 * already converted, to `rgb(0, 0, 0)`.
 *
 * Left as a comment rather than deleted silently, because "the token reads back
 * as a colour" is the property three canvases depend on (`tokens.css` argues
 * it) and this is the second place it is observable. If a future change
 * un-registers the palette, these two assertions go red here first.
 */
