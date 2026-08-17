/** `.cmp-passage`'s border geometry, which arrived with the `evidence` widget.
 *
 * Its own file rather than a second `it` inside `GraphWidget.browser.test.tsx`,
 * where it was first filed: this is the `evidence` widget's only geometry
 * measurement, and living inside the graph widget's suite meant deleting the
 * graph widget would silently delete it. Nothing about the assertion is about
 * graphs.
 *
 * CLAUDE.md is explicit that no gate catches this and that jsdom cannot see
 * it: `getComputedStyle` there returns only what an inline style said. The
 * rule pairs `border: 0` with `border-left: 2px`, and the failure it guards
 * against is the `border-solid` trap -- a directional width beside an
 * all-sides style leaves the other three at the browser's `medium` (~3px), so
 * a rule meant for one edge draws a box.
 *
 * **Proved red** by deleting the `border: 0` line from `.cmp-passage` and
 * adding `border-style: solid`: `borderTopWidth` comes back as `3px`.
 */
import { expect, it } from 'vitest'
import { render } from 'vitest-browser-react'

it('draws the passage rule on one edge only', async () => {
  const screen = await render(
    <div className="md doc">
      <figure className="cmp-passage">
        <blockquote>cunctos populos</blockquote>
      </figure>
    </div>,
  )

  const passage = screen.container.querySelector('.cmp-passage') as HTMLElement
  const style = getComputedStyle(passage)

  expect(style.borderLeftWidth).toBe('2px')
  expect(style.borderTopWidth).toBe('0px')
  expect(style.borderRightWidth).toBe('0px')
  expect(style.borderBottomWidth).toBe('0px')
})
