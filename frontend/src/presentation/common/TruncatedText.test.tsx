import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import { TruncatedText } from './TruncatedText.tsx'

/** What jsdom can hold about clipped text, which is the half that is not the
 *  measurement.
 *
 *  Nothing is ever clipped here: `scrollWidth` and `clientWidth` are both 0 in
 *  jsdom, so the component always takes its unclipped branch. That makes this
 *  file the *negative* assertions -- text that fits stays out of the tab order
 *  and grows no tooltip -- and it is a real claim rather than a consolation
 *  prize, because attaching a tooltip unconditionally is the design that was
 *  rejected and this is what would catch it coming back.
 *
 *  The positive claim -- clipped text gains a tooltip and a focus stop -- is
 *  in `TruncatedText.browser.test.tsx`, where a box has a width.
 */

it('renders the text', () => {
  render(<TruncatedText text="a question long enough to be worth clipping" />)
  expect(screen.getByText('a question long enough to be worth clipping')).toBeInTheDocument()
})

it('keeps the class it was given, so the truncation rules land on the text itself', () => {
  // Not cosmetic: the class carries `overflow: hidden` and `min-width: 0`, and
  // if a wrapper took its place the wrapper would become the flex item and
  // nothing would truncate. This asserts the element count stays one.
  render(<TruncatedText text="apollo" className="ent-ref-name" />)
  expect(screen.getByText('apollo')).toHaveClass('ent-ref-name')
})

it('adds no focus stop and no description while the text fits', () => {
  render(<TruncatedText text="apollo" />)
  const text = screen.getByText('apollo')
  expect(text).not.toHaveAttribute('tabindex')
  // A tooltip would have wired this from trigger to content. Its absence is
  // the assertion: seven ref sites, several in lists, and a tab order padded
  // with stops offering a sentence already on screen is the cost that was
  // being avoided.
  expect(text).not.toHaveAttribute('aria-describedby')
})
