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

/** The four elements the rules in `tokens.css` actually name.
 *
 * **This file asserted on `<button>` and nothing else until 2026-08-29**, and
 * the rules it guards have always read `button, input, textarea, select`
 * (`tokens.css`, the two `@layer base` blocks). Three of the four were
 * untested, which is the same shape as the defect: a selector list is one rule
 * to the cascade and four elements to a reader, and a test that samples one of
 * them proves the rule fires *somewhere*.
 *
 * It is not merely a completeness argument. The three untested elements are the
 * ones the UA dresses hardest — a `<select>` and an `<input>` each carry a
 * native appearance a `<button>` does not — so if any of the four were going to
 * resist a utility for a reason other than the layer, it would be one of these.
 */
const CONTROLS = ['button', 'input', 'textarea', 'select'] as const

type Control = (typeof CONTROLS)[number]

/** A bare control of each kind, carrying only the class under test.
 *
 * `<select>` gets one `<option>` because a select with no options has no
 * intrinsic size in some engines, and a zero-height box is a bad thing to be
 * measuring a font on. Nothing else here is styled. */
const control = (kind: Control, className?: string) => {
  const props = className ? { className } : {}
  switch (kind) {
    case 'button':
      return (
        <button type="button" {...props}>
          press
        </button>
      )
    case 'input':
      return <input type="text" readOnly value="typed" {...props} />
    case 'textarea':
      return <textarea readOnly value="typed" {...props} />
    case 'select':
      return (
        <select {...props}>
          <option>one</option>
        </select>
      )
  }
}

/** Read through the render's own container rather than through a query.
 *
 *  Several cases below render twice -- the dressed control and the bare one, so
 *  the comparison is against a measured default rather than a token -- and both
 *  are in the document at once. A `data-testid` query is document-wide, so it
 *  found two and threw; the container is the one node this render owns. */
/** A font stack as a list of names, with the engine's quoting removed.
 *
 *  `getPropertyValue` hands back the token exactly as `theme.css` authored it
 *  (`'Segoe UI'`, single-quoted) and `getComputedStyle().fontFamily` re-serialises
 *  the same stack with double quotes. Measured, not guessed: the first draft of
 *  the case below compared the two strings and failed on that difference alone,
 *  with both sides naming the identical fonts. What is being asserted is which
 *  stack the control ended up on, not how Chromium prints one. */
const families = (stack: string) =>
  stack
    .split(',')
    .map((name) => name.trim().replace(/^['"]|['"]$/g, ''))
    .filter((name) => name.length > 0)

const drawn = (kind: Control, className?: string) => {
  const { container } = render(control(kind, className))
  return computed(container.firstElementChild!)
}

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

/** The same four claims, on all four elements, plus the one leg of the
 *  shorthand nothing measured.
 *
 * **`font-family` is the gap, and it is the one CLAUDE.md's own account points
 * at.** The entry says `font: inherit` "reaches furthest because it is a
 * *shorthand*: it sets `font-size`, so the size utilities went silently along
 * with the colour ones". `font-size` is one leg. `font-family` is another, and
 * until now nothing in this repository asserted on it -- so a `font-mono` on an
 * input was in exactly the state `text-xs` on a button was in before #313: in
 * the class attribute, in the bundle, and never meeting the rule.
 *
 * Measured 2026-08-29: with `tokens.css`'s `font: inherit` block unwrapped from
 * its `@layer base`, the colour, size and family cases below go red on every
 * one of the four elements, reporting the default's own value -- and with the
 * background block unwrapped, so does the background case. That is how they
 * were proved rather than assumed.
 *
 * **What would happen if this file stopped running** is not a hypothetical:
 * `base-layer.browser.test.tsx` did exactly that and asserted nothing for the
 * life of the fix it was written to guard (BACKLOG B160). A file that dies at
 * import reads, in a summary line, like a file that passes. There is no
 * assertion a file can make about its own execution, so the defence is
 * structural and lives outside it: the `browser` CI job reports a suite that
 * fails to import as a failed *suite* rather than as zero tests. That job
 * landed on 2026-08-29 and is what makes this file's silence detectable.
 */
it.each(CONTROLS)('lets a background utility beat the default on a <%s>', (kind) => {
  expect(drawn(kind, 'bg-transparent').backgroundColor).toBe('rgba(0, 0, 0, 0)')
})

it.each(CONTROLS)('lets a colour utility beat the default on a <%s>', (kind) => {
  const root = computed(document.documentElement)
  const accent = root.getPropertyValue('--accent').trim()
  const fg = root.getPropertyValue('--fg').trim()
  expect(accent).not.toBe(fg)

  expect(drawn(kind, 'text-accent').color).toBe(accent)
})

it.each(CONTROLS)('lets a size utility beat `font: inherit` on a <%s>', (kind) => {
  const small = parseFloat(drawn(kind, 'text-xs').fontSize)
  const plain = parseFloat(drawn(kind).fontSize)
  expect(small).toBeLessThan(plain)
})

it.each(CONTROLS)('lets a family utility beat `font: inherit` on a <%s>', (kind) => {
  // The leg of the shorthand nothing measured. Compared against the two theme
  // stacks rather than against a literal: what is asserted is that the control
  // moved off the page's family onto the one the utility names, not how
  // Chromium quotes a font list.
  const root = computed(document.documentElement)
  const sans = families(root.getPropertyValue('--font-sans'))
  const mono = families(root.getPropertyValue('--font-mono'))
  expect(sans).not.toEqual(mono)

  // The default first, so the claim below is against a measured value rather
  // than against the token the rule was written from.
  expect(families(drawn(kind).fontFamily)).toEqual(sans)
  expect(families(drawn(kind, 'font-mono').fontFamily)).toEqual(mono)
})

it.each(CONTROLS)('still dresses a <%s> that says nothing', (kind) => {
  // The half that must not regress, on all four rather than on the one. A
  // layered default has to keep beating *nothing*, or an unclassed control goes
  // back to the UA's own colours -- about 1.15:1 against this theme's text, the
  // measurement `tokens.css` records for a bare `<button>`.
  const root = computed(document.documentElement)
  expect(drawn(kind).backgroundColor).toBe(root.getPropertyValue('--bg').trim())
  expect(drawn(kind).color).toBe(root.getPropertyValue('--fg').trim())
})
