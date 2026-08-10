import { render as renderBare, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { expect, it, vi } from 'vitest'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { Confirm } from './Confirm.tsx'

/** A host, because `Confirm` is a `Drawer` and a `Drawer` is an `Overlay`,
 *  which renders nothing without one. That chain is the composition this file
 *  is about, so needing the host here is the contract showing through rather
 *  than test scaffolding. */
const render = (ui: ReactElement) => renderBare(<OverlayHost>{ui}</OverlayHost>)

/** What `Confirm` promises on top of `Drawer`: one paragraph per line, two
 *  buttons wired to two different callbacks, and the tone on the destructive
 *  one.
 *
 *  Proved red first, each against a single deliberate break: `lines.join(' ')`
 *  into one paragraph, the two `onClick`s swapped, and `tone` dropped from the
 *  confirm button.
 *
 *  The Escape case below is inherited from `Drawer` and is asserted here
 *  anyway, because "Escape means cancel, not confirm" is the part a reader of
 *  `Confirm` needs to be true and the composition is what makes it so. It
 *  would fail if `Confirm` ever grew its own container. */

const props = {
  title: 'Take over this session?',
  lines: ['The agent stops where it is.', 'Everything written so far survives.'],
  confirmLabel: 'Take over',
}

it('renders one paragraph per line rather than one run-on sentence', () => {
  const { container } = render(<Confirm {...props} onConfirm={() => {}} onCancel={() => {}} />)

  // These sentences are deliberately separate thoughts; joining them with
  // newlines was only ever a limitation of `window.confirm`. Asserting the
  // count, not just the text, is what catches a join.
  const paragraphs = Array.from(container.querySelectorAll('.confirm p')).map((p) => p.textContent)
  expect(paragraphs).toEqual([
    'The agent stops where it is.',
    'Everything written so far survives.',
  ])
})

it('calls onConfirm from the confirm button and nothing else', async () => {
  const user = userEvent.setup()
  const onConfirm = vi.fn()
  const onCancel = vi.fn()
  render(<Confirm {...props} onConfirm={onConfirm} onCancel={onCancel} />)

  await user.click(screen.getByRole('button', { name: 'Take over' }))

  expect(onConfirm).toHaveBeenCalledTimes(1)
  expect(onCancel).not.toHaveBeenCalled()
})

it('calls onCancel from Cancel, from Close, and from Escape', async () => {
  const user = userEvent.setup()
  const onConfirm = vi.fn()
  const onCancel = vi.fn()
  render(<Confirm {...props} onConfirm={onConfirm} onCancel={onCancel} />)

  await user.click(screen.getByRole('button', { name: 'Cancel' }))
  await user.click(screen.getByRole('button', { name: 'Close' }))
  await user.keyboard('{Escape}')

  // Three routes out, one of them the drawer's own. The assertion that matters
  // is the second: an irreversible action must not be reachable by dismissing
  // the dialog.
  expect(onCancel).toHaveBeenCalledTimes(3)
  expect(onConfirm).not.toHaveBeenCalled()
})

it('carries the caller’s tone on the confirming button only', () => {
  render(
    <Confirm
      {...props}
      confirmLabel="Delete"
      tone="danger"
      onConfirm={() => {}}
      onCancel={() => {}}
    />,
  )

  // The class is the only observable form the tone takes today. This assertion
  // is the one most coupled to the current implementation, and it is here
  // because a destructive confirm rendering in the default tone is a real
  // defect that nothing else in this suite would notice.
  expect(screen.getByRole('button', { name: 'Delete' })).toHaveClass('btn-danger')
  expect(screen.getByRole('button', { name: 'Cancel' })).not.toHaveClass('btn-danger')
})

it('is a modal dialog named by its question', () => {
  render(<Confirm {...props} onConfirm={() => {}} onCancel={() => {}} />)

  // `title` serves as both the heading and the accessible name here, which is
  // right for a confirm: the question *is* the name of the dialog.
  expect(screen.getByRole('dialog', { name: 'Take over this session?' })).toHaveAttribute(
    'aria-modal',
    'true',
  )
})
