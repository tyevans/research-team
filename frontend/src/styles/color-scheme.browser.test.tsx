import { render } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'

/** The one declaration that tells the browser which way round this console is.
 *
 * In the browser suite rather than jsdom, and not as a convenience: jsdom
 * applies no stylesheet, so `getComputedStyle(document.documentElement)
 * .colorScheme` there is whatever an inline style said and is `''` for a page
 * that never set one. It cannot tell a console that declared a scheme from one
 * that declared nothing, which is exactly what these tests separate.
 *
 * **Rewritten rather than extended when light mode landed**, as the roadmap
 * said it would be. It used to assert one thing -- that the UA paints a control
 * dark -- because `color-scheme: dark` was a constant. It is now a function of
 * `data-theme`, so the same measurement is taken in each of the three states.
 *
 * The technique is unchanged and is the reason this file is worth copying:
 * render a control the stylesheet does **not** paint, and read the user
 * agent's own answer. That is the only way to see `color-scheme` at all --
 * `background` does not reach a control the UA draws through `appearance`, so
 * a checkbox, a radio, a `<select>` popup and a date picker follow this
 * declaration and nothing else in the repository.
 */

/** A control whose background the stylesheet does not set, so what it paints is
 *  the UA's own answer. `revert` rather than a bare `<input>`: `tokens.css`
 *  gives every field `background: var(--bg)`, which would hide the very thing
 *  being measured. */
const uaBackground = (el: Element): number[] =>
  getComputedStyle(el)
    .backgroundColor.match(/\d+/g)!
    .slice(0, 3)
    .map((n) => Number(n))

const declared = document.documentElement.getAttribute('data-theme')
afterEach(() => {
  if (declared === null) document.documentElement.removeAttribute('data-theme')
  else document.documentElement.setAttribute('data-theme', declared)
})

const under = (value: string) => {
  document.documentElement.setAttribute('data-theme', value)
  const { container } = render(
    <>
      <input data-testid="field" style={{ background: 'revert' }} />
      <button type="button" data-testid="button" style={{ background: 'revert' }}>
        press
      </button>
    </>,
  )
  return ['field', 'button'].map((id) =>
    uaBackground(container.querySelector(`[data-testid="${id}"]`)!),
  )
}

it('leaves the browser drawing its own controls dark under the dark theme', () => {
  // Measured in Chromium: `rgb(59, 59, 59)` for the field and `rgb(107, 107,
  // 107)` for the button under `dark`, against `rgb(255, 255, 255)` and
  // `rgb(239, 239, 239)` under the default. The threshold is halfway between
  // the two families rather than the exact values, because the UA's dark greys
  // are a browser's business and a Chromium release is allowed to nudge them;
  // which side of light they fall on is not.
  //
  // What it fails on: deleting `:root[data-theme='dark'] { color-scheme: dark }`
  // from `tokens.css`. Proved red that way -- both controls come back above
  // 200, because the headless browser's own preference is light.
  for (const [r, g, b] of under('dark')) expect(Math.max(r!, g!, b!)).toBeLessThan(160)
})

it('leaves the browser drawing its own controls light under the light theme', () => {
  // The half that did not exist before, and the one that would have caught a
  // light mode wired only into the tokens: a console whose *palette* flips but
  // whose `color-scheme` does not gets a white page with a black `<select>`
  // popup and an unreadable date picker, and every colour assertion in
  // `theme.browser.test.tsx` still passes.
  //
  // What it fails on: deleting `:root[data-theme='light']`. That one is
  // **weaker than it looks and is stated rather than hidden** -- with the rule
  // gone the document falls through to `:root { color-scheme: light dark }`,
  // and the headless browser prefers light, so it still passes. It fails when
  // the rule is deleted *and* the run is on a dark desktop. The assertion that
  // does not depend on the environment is the dark one above and the explicit-
  // choice test in `theme.browser.test.tsx`, which emulates the preference.
  for (const [r, g, b] of under('light')) expect(Math.min(r!, g!, b!)).toBeGreaterThan(160)
})

it('does not make the stylesheet own background redundant', () => {
  // The question #39 left open, answered here so nobody has to re-open it: the
  // UA's dark field is `rgb(59, 59, 59)` and `--bg` is `#0b0d10`, so deleting
  // `background: var(--bg)` from `tokens.css` would not leave fields matching
  // the page -- it would leave a bare `<input>` and a `.input` two shades apart
  // on the same line. This fails if the two ever coincide, which is the only
  // condition under which that rule could go.
  //
  // Asserted in **both** schemes since light mode landed. In light the gap is
  // smaller -- the UA's field is white and `--bg` is #f7f6f3 -- which is
  // precisely why it is worth measuring rather than assuming: "close enough to
  // white" is where this rule would first look droppable.
  for (const scheme of ['dark', 'light']) {
    document.documentElement.setAttribute('data-theme', scheme)
    const { container } = render(
      <>
        <input data-testid="themed" />
        <input data-testid="ua" style={{ background: 'revert' }} />
      </>,
    )
    expect(uaBackground(container.querySelector('[data-testid="themed"]')!), scheme).not.toEqual(
      uaBackground(container.querySelector('[data-testid="ua"]')!),
    )
  }
})
