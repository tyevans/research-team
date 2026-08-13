import { render } from '@testing-library/react'
import { expect, it } from 'vitest'

/** The one declaration that tells the browser which way round this console is.
 *
 * In the browser suite rather than jsdom, and not as a convenience: jsdom
 * applies no stylesheet, so `getComputedStyle(document.documentElement)
 * .colorScheme` there is whatever an inline style said and is `''` for a page
 * that never set one. It cannot tell a console that declared `dark` from one
 * that declared nothing, which is exactly the two states this test separates.
 *
 * The two tests guard different lines and only the first guards this one:
 * deleting `color-scheme: dark` fails it and leaves the second green, because
 * a UA field is a different colour from `--bg` whichever scheme is in force.
 * The second is there for the rule underneath, and says so.
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

it('leaves the browser drawing its own controls dark', () => {
  const { container } = render(
    <>
      <input data-testid="field" style={{ background: 'revert' }} />
      <button type="button" data-testid="button" style={{ background: 'revert' }}>
        press
      </button>
    </>,
  )

  // Measured in Chromium: `rgb(59, 59, 59)` for the field and `rgb(107, 107,
  // 107)` for the button under `dark`, against `rgb(255, 255, 255)` and
  // `rgb(239, 239, 239)` under the default. The threshold is halfway between
  // the two families rather than the exact values, because the UA's dark greys
  // are a browser's business and a Chromium release is allowed to nudge them;
  // which side of light they fall on is not.
  for (const id of ['field', 'button']) {
    const [r, g, b] = uaBackground(container.querySelector(`[data-testid="${id}"]`)!)
    expect(Math.max(r!, g!, b!)).toBeLessThan(160)
  }
})

it('does not make the stylesheet own background redundant', () => {
  // The question #39 left open, answered here so nobody has to re-open it: the
  // UA's dark field is `rgb(59, 59, 59)` and `--bg` is `#0b0d10`, so deleting
  // `background: var(--bg)` from `tokens.css` would not leave fields matching
  // the page -- it would leave a bare `<input>` and a `.input` two shades apart
  // on the same line. This fails if the two ever coincide, which is the only
  // condition under which that rule could go.
  const { container } = render(
    <>
      <input data-testid="themed" />
      <input data-testid="ua" style={{ background: 'revert' }} />
    </>,
  )

  expect(uaBackground(container.querySelector('[data-testid="themed"]')!)).not.toEqual(
    uaBackground(container.querySelector('[data-testid="ua"]')!),
  )
})
