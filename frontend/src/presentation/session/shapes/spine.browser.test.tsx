import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ToolResult } from './ToolResult.tsx'
import { hitListMessage, hitListMessageWithExpander } from './fixtures.ts'

/** The spine and the expander, measured.
 *
 * Both assertions here are computed styles, which is why this is a browser
 * test rather than a cheaper jsdom one: jsdom applies no stylesheet and
 * `getComputedStyle` returns only what an inline style said, so in jsdom the
 * class is in the attribute, the rule is in the bundle, and the two never
 * meet. A jsdom version of either test below would pass against a stylesheet
 * that had been deleted.
 */
describe('the spine', () => {
  it('draws one edge, not four', () => {
    // `border-solid` beside one directional width gives the other three sides
    // a style with no width, and they fall back to the browser's `medium`
    // (~3px): a rule meant for one edge draws a box. This build imports no
    // Tailwind preflight, so nothing else zeroes them.
    const { getAllByTestId } = render(<ToolResult message={hitListMessage} phase="settled" />)
    const style = getComputedStyle(getAllByTestId('stream-gutter')[0]!)
    expect(style.borderLeftWidth).toBe('1px')
    expect(style.borderTopWidth).toBe('0px')
    expect(style.borderRightWidth).toBe('0px')
    expect(style.borderBottomWidth).toBe('0px')
  })

  it('runs the spine behind the glyph rather than stopping at it', () => {
    // The glyph is haloed in the panel's own background so the line reads as
    // continuous. If the halo were transparent the spine would strike through
    // every mark; if the glyph did not overlap the line at all the gutter
    // would read as two columns.
    const { getAllByTestId } = render(<ToolResult message={hitListMessage} phase="settled" />)
    const gutter = getAllByTestId('stream-gutter')[0]!.getBoundingClientRect()
    const glyph = getAllByTestId('stream-glyph')[0]!.getBoundingClientRect()
    expect(glyph.left).toBeLessThan(gutter.left)
    expect(glyph.right).toBeGreaterThan(gutter.left)
  })
})

describe('the expander', () => {
  it('gets the size its own class asks for', () => {
    // `tokens.css` sets `font: inherit` on every bare button. It is layered
    // now, so a class here wins -- but `font` is a *shorthand*, so before that
    // fix it set `font-size` too and nothing about `text-xs` suggests it is
    // competing with a `font` declaration. Red if the expander is ever styled
    // with a utility instead of `.stream-exp`.
    const { getByRole } = render(
      <ToolResult message={hitListMessageWithExpander} phase="settled" />,
    )
    expect(getComputedStyle(getByRole('button')).fontSize).toBe('10px')
  })

  it('carries no background of its own', () => {
    // The bare-button default paints `--bg` opaquely. On a row that is already
    // indented behind a rule that reads as a box drawn around the control.
    const { getByRole } = render(
      <ToolResult message={hitListMessageWithExpander} phase="settled" />,
    )
    expect(getComputedStyle(getByRole('button')).backgroundColor).toBe('rgba(0, 0, 0, 0)')
  })
})
