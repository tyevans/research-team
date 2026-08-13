import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'

import { TabList, TabPanel, Tabs } from './Tabs.tsx'

/** What tabs owe, and the one deviation from the usual advice.
 *
 * The panel wiring is the reason this is `Tabs` and not `Choices`: a
 * `role="tab"` points at a `role="tabpanel"` and both halves have to exist for
 * either to mean anything. The row of buttons it replaces had neither role and
 * no relationship between the control and what it opened.
 *
 * jsdom judges this fairly — roles, relationships, focus and key routing are
 * what it models, and nothing here floats. What it cannot show is the skin,
 * which moved to `[data-state='active']` in the same commit and is looked at in
 * `Tabs.stories.tsx`.
 */

const OPTIONS = [
  { id: 'content', label: 'contents' },
  { id: 'history', label: 'history' },
]

const Fixture = ({ onOpen = () => {} }: { onOpen?: (value: string) => void }) => {
  const [value, setValue] = useState('content')
  return (
    <Tabs
      value={value}
      onValueChange={(next) => {
        setValue(next)
        onOpen(next)
      }}
    >
      <TabList label="File view" options={OPTIONS} />
      <TabPanel value="content">the file</TabPanel>
      <TabPanel value="history">every revision</TabPanel>
    </Tabs>
  )
}

it('shows one panel and names which tab opened it', async () => {
  const user = userEvent.setup()
  render(<Fixture />)

  // Only the open panel is in the document at all, which is what the ternary
  // this replaced did by hand — a panel that fetches does not fetch until it is
  // looked at.
  expect(screen.getByText('the file')).toBeInTheDocument()
  expect(screen.queryByText('every revision')).not.toBeInTheDocument()

  const panel = screen.getByRole('tabpanel')
  const open = screen.getByRole('tab', { name: 'contents' })
  expect(open).toHaveAttribute('aria-selected', 'true')
  // The relationship in both directions. This is the assertion that fails
  // against the row of unadorned `<button>`s this replaced, and the reason
  // `Choices` is a separate component: pointing `aria-controls` at a panel that
  // does not exist would be worse than claiming nothing.
  expect(open).toHaveAttribute('aria-controls', panel.getAttribute('id'))
  expect(panel).toHaveAttribute('aria-labelledby', open.getAttribute('id'))

  await user.click(screen.getByRole('tab', { name: 'history' }))
  expect(screen.getByText('every revision')).toBeInTheDocument()
  expect(screen.queryByText('the file')).not.toBeInTheDocument()
})

it('is one tab stop, and an arrow key does not open what it lands on', async () => {
  const opened = vi.fn()
  const user = userEvent.setup()
  render(<Fixture onOpen={opened} />)

  await user.tab()
  expect(screen.getByRole('tab', { name: 'contents' })).toHaveFocus()

  await user.keyboard('{ArrowRight}')
  expect(screen.getByRole('tab', { name: 'history' })).toHaveFocus()

  // `activationMode="manual"`, and this is the assertion that fails if it is
  // dropped: with Radix's default the arrow key alone would have mounted
  // `FileHistory` and fired its request, for a panel the reader was passing
  // over rather than asking for. The cost is the extra press below.
  expect(opened).not.toHaveBeenCalled()
  expect(screen.queryByText('every revision')).not.toBeInTheDocument()

  await user.keyboard('{Enter}')
  expect(opened).toHaveBeenCalledWith('history')
})
