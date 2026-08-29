import { render } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { userEvent } from 'vitest/browser'

import { Button } from './primitives.tsx'

/** That the quiet button's *hover* state follows the reader's scheme.
 *
 * **The defect, measured on 2026-08-28.** `.btn-quiet` set its border and its
 * hover fill from three dark-scheme hexes written literally -- `#3a2b2c`,
 * `#241517`, `#543336` -- while its ink came from `--del-fg`, which does have
 * a light column. In light mode "Abandon this course" on the course page drew a
 * near-black border and filled near-black under a dark red, which is the one
 * control on that page that ignored the theme. `.btn-danger`'s hover carried
 * the same defect in two more hexes.
 *
 * **Why a browser test, and why hover specifically.** jsdom applies no
 * stylesheet, so `getComputedStyle` there returns what an inline style said:
 * the broken build, the fixed build and a build with no stylesheet at all read
 * the same empty string. And a `:hover` rule is reachable only by a real
 * pointer -- the whole defect lived in a state no rendered-once measurement
 * enters.
 *
 * **Stated as the sign of the difference, not as values**, so the palette can
 * be retuned without touching this file. What it fails on: any of those five
 * declarations going back to a literal colour, or a new quiet-tone colour added
 * to `shell.css` rather than to `theme.css`. Proved red by restoring
 * `background: #241517` on the hover rule, which pins the light fill dark and
 * inverts the luminance claim below.
 */

const declared = document.documentElement.getAttribute('data-theme')

afterEach(() => {
  if (declared === null) document.documentElement.removeAttribute('data-theme')
  else document.documentElement.setAttribute('data-theme', declared)
})

const luminance = (rgb: string) => {
  const [r, g, b] = rgb.match(/\d+/g)!.slice(0, 3).map(Number)
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!
}

/** The hovered button's fill, border and ink in the scheme asked for.
 *
 * Each theme gets its own render and the values are copied out as strings: a
 * computed-style object stays live, so measuring both schemes off one element
 * and comparing afterwards reads the second scheme twice -- the trap
 * `theme.browser.test.tsx` records hitting.
 */
const hovered = async (theme: 'light' | 'dark', tone: 'quiet' | 'danger') => {
  document.documentElement.setAttribute('data-theme', theme)
  const { getByRole, unmount } = render(<Button tone={tone}>Abandon this course</Button>)
  const button = getByRole('button')
  await userEvent.hover(button)
  const style = getComputedStyle(button)
  const measured = {
    fill: style.backgroundColor,
    border: style.borderTopColor,
    ink: style.color,
  }
  unmount()
  return measured
}

it.each(['quiet', 'danger'] as const)(
  'fills the %s button toward the page it is on, in either scheme',
  async (tone) => {
    const dark = await hovered('dark', tone)
    const light = await hovered('light', tone)

    // The claim: the hover fill and the border move with the scheme at all. A
    // literal hex gives the same three strings under both.
    expect(light).not.toEqual(dark)

    // And the right way round -- light mode's fill is lighter than dark mode's,
    // which is what "near-black button on a white page" failed.
    expect(luminance(light.fill)).toBeGreaterThan(luminance(dark.fill))
    expect(luminance(light.border)).toBeGreaterThan(luminance(dark.border))

    // Readable, not merely themed: the ink is darker than its own fill in
    // light and lighter than it in dark. A fill that follows the scheme under
    // an ink that does not is the same unreadable button.
    expect(luminance(light.ink)).toBeLessThan(luminance(light.fill))
    expect(luminance(dark.ink)).toBeGreaterThan(luminance(dark.fill))
  },
)
