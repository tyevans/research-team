import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'

import { Choices } from './Choices.tsx'

/** What a radiogroup owes, which the two hand-rolled ones did not pay.
 *
 * `FileView`'s `TabGroup` and `TopicQueue`'s `role="radiogroup"` both declared
 * a group of radios and left every option its own tab stop with no arrow keys.
 * The first two tests here fail against that arrangement, so they state what
 * the conversion bought rather than guarding a regression. The third is a
 * genuine guard, over a line of ours rather than of the library's.
 *
 * jsdom judges all of this fairly -- roles, focus and keyboard routing are what
 * it models. What it cannot show is that the pressed option looks pressed: the
 * skin moved from a `.active` class to `[data-state='on']` in the same commit,
 * and no stylesheet is applied here. `Choices.stories.tsx` is where that is
 * looked at.
 */

const OPTIONS = [
  { id: 'rendered', label: 'rendered' },
  { id: 'source', label: 'source' },
] as const

const Fixture = ({ onChange = () => {} }: { onChange?: (value: string) => void }) => {
  const [value, setValue] = useState<'rendered' | 'source'>('rendered')
  return (
    <Choices
      label="How to show this file"
      options={OPTIONS}
      value={value}
      onValueChange={(next) => {
        setValue(next)
        onChange(next)
      }}
    />
  )
}

it('is one tab stop for the group, not one per option', async () => {
  const user = userEvent.setup()
  render(<Fixture />)

  await user.tab()
  expect(screen.getByRole('radio', { name: 'rendered' })).toHaveFocus()

  // Out of the group entirely, rather than on to `source`. This is the half of
  // the radiogroup contract the hand-rolled versions never had: a reader
  // tabbing through the header passes the whole choice in one press, and moves
  // *within* it with the arrows below.
  await user.tab()
  expect(screen.getByRole('radio', { name: 'source' })).not.toHaveFocus()
})

it('moves within the group with the arrow keys', async () => {
  const chosen = vi.fn()
  const user = userEvent.setup()
  render(<Fixture onChange={chosen} />)

  await user.tab()
  await user.keyboard('{ArrowRight}')
  expect(screen.getByRole('radio', { name: 'source' })).toHaveFocus()

  await user.keyboard(' ')
  expect(chosen).toHaveBeenCalledWith('source')
})

/** **Selection does not follow focus here, and in a browser it does.**
 *
 * The assertion this file wanted was `{ArrowRight}` alone leaving `source`
 * checked, which is what the APG asks of a radiogroup and what `RadioGroup` was
 * chosen over `ToggleGroup` to get. jsdom reports focus on `source` and
 * `aria-checked="true"` still on `rendered`: Radix decides "was this focus
 * change caused by an arrow key" from a `keydown` listener on `document`, and
 * that reads differently under jsdom's event loop than under a real one.
 *
 * So the space press above is not the contract -- it is the part of the
 * contract this environment can see, and the test would pass against a
 * component with no arrow-key selection at all. Checked in Chromium instead, at
 * 1440px on `common-tabs--file-view-header`: one Tab into the group, one
 * ArrowRight, and the panel switches to source with no further press. Recorded
 * here because a reader comparing this file to the docstring in `Choices.tsx`
 * would otherwise find the claim unsupported.
 *
 * This is task #12's shape again -- the third finding in a row whose real
 * assertion cannot be written in this repo. */

it('cannot be left with nothing chosen', async () => {
  const chosen = vi.fn()
  const user = userEvent.setup()
  render(<Fixture onChange={chosen} />)

  await user.click(screen.getByRole('radio', { name: 'rendered' }))

  // A test over the dependency rather than over our code, and worth having for
  // that reason: `ToggleGroup`, the component this was first built on, treats a
  // press on the chosen item as a deselection and reports `''`. There is no
  // "neither rendered nor source", and in `FileView` an empty value would change
  // the query key and refetch the document for an audience the server has no
  // name for. This is the assertion that fails if anyone swaps the library back.
  expect(chosen).not.toHaveBeenCalled()
  expect(screen.getByRole('radio', { name: 'rendered' })).toHaveAttribute('aria-checked', 'true')
})
