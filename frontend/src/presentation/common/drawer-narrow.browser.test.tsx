import { composeStories } from '@storybook/react-vite'
import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { afterEach, expect, it } from 'vitest'

import { BREAKPOINTS } from '@presentation/layout/layout-tokens.ts'
import { DEFAULT_VIEWPORT } from '../../test/browser-viewport.ts'

import * as stories from './Drawer.stories.tsx'

/** The drawer gives up its width below `--bp-narrow`, and until now nobody had
 *  looked.
 *
 * `Drawer.tsx` says it plainly and marks it as a behaviour change: `.drawer`
 * "stays on the class list and is now a hook rather than a rule", because
 * `responsive.css` narrows this panel to full width below 820px and "it now
 * actually applies" -- an unlayered `.drawer` beats a `@layer utilities` one,
 * where before it lost outright. The comment ends "that is a behaviour change,
 * at one breakpoint, in the direction the rule already stated."
 *
 * A behaviour change stated in a comment and measured nowhere is the shape
 * `CLAUDE.md` opens with. **Measured on 2026-08-23 in Chromium**: at 500px the
 * drawer is 500px wide, at `left: 0`, with `min-width: 0` and `max-width:
 * none` -- so the stylesheet is beating all three of the utilities
 * (`w-[42vw] max-w-[640px] min-w-[360px]`), not just one.
 *
 * **Why this does not use `resizeViewport`.** That helper polls `Split`'s
 * React-written `grid-template-columns`, and a drawer story has no split to
 * poll -- it would wait forever. The deeper reason it is not needed here is
 * the one worth keeping: the drawer's narrow form is a **stylesheet media
 * query**, not a React branch. There is no commit to wait for, so the
 * element's own geometry is the signal rather than a proxy for one. That is
 * exactly the case the helper's docstring says geometry alone is *not* enough
 * for -- and it is not enough there because `Split` writes a template from
 * JavaScript. Two different mechanisms, two different waits.
 */
const { Padded } = composeStories(stories)

const drawer = () => document.body.querySelector('.drawer')

afterEach(async () => {
  await page.viewport(DEFAULT_VIEWPORT.width, DEFAULT_VIEWPORT.height)
})

it('takes its share of a wide viewport, capped', async () => {
  await page.viewport(1440, 900)
  await render(<Padded />)

  await expect.poll(() => drawer()?.getBoundingClientRect().width).toBeGreaterThan(0)
  const box = drawer()!.getBoundingClientRect()

  // 42vw of 1440 is 604.8, under the 640 cap and over the 360 floor.
  expect(Math.round(box.width)).toBe(605)
  expect(Math.round(box.right)).toBe(1440)
})

/** The behaviour change the comment states, measured. */
it('goes full width below the narrow breakpoint', async () => {
  await page.viewport(500, 900)
  await render(<Padded />)

  await expect.poll(() => Math.round(drawer()?.getBoundingClientRect().width ?? 0)).toBe(500)

  const box = drawer()!.getBoundingClientRect()
  expect(Math.round(box.left)).toBe(0)

  // All three utilities are overridden, not just the width: a `min-width` of
  // 360 surviving here would be invisible at 500 and would clip the drawer on
  // any phone-sized viewport.
  const style = getComputedStyle(drawer()!)
  expect(style.minWidth).toBe('0px')
  expect(style.maxWidth).toBe('none')
})

/** The boundary itself, from the token rather than from a literal -- a test
 *  that hard-codes 821 goes quietly wrong the day the breakpoint moves. */
it('is still full width one pixel below the breakpoint', async () => {
  await page.viewport(BREAKPOINTS.narrow - 1, 900)
  await render(<Padded />)

  await expect
    .poll(() => Math.round(drawer()?.getBoundingClientRect().width ?? 0))
    .toBe(BREAKPOINTS.narrow - 1)
})
