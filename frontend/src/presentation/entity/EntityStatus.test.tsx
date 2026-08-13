import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import { EntityStatus } from './EntityStatus.tsx'

/** That the tone reaches the markup.
 *
 * `status.test.ts` already asserts which tone each status earns; this file
 * asserts the chip actually renders it. The two are separate on purpose and
 * the gap between them was real: a mutation that pinned the chip to
 * `tone: 'neutral'` — so every failure rendered as an ordinary status —
 * **survived the whole suite**, because the domain tests passed the rule and
 * nothing checked the component obeyed it. A rule that is right and unapplied
 * looks exactly like a rule that works.
 */

it('paints a failure with the failing tone', () => {
  render(<EntityStatus status="failed" />)
  // `closest` rather than the matched element: the status word is its own
  // span now, so that it can be told not to shrink when the reason beside it
  // has to. The tone stays on the chip, which is what carries the chrome.
  expect(screen.getByText('failed').closest('.ent-status')).toHaveClass('ent-status-bad')
})

it('paints a gate as held rather than as a failure', () => {
  // C-F46 end to end: the domain says `held`, and this is where a reader sees
  // it. Filing a pause with the failures is what made a normal wait look like
  // a fault.
  const { container } = render(<EntityStatus status="human_gate" />)
  const chip = container.querySelector('.ent-status')
  expect(chip).toHaveClass('ent-status-held')
  expect(chip).not.toHaveClass('ent-status-bad')
})

it('gives only queue_empty the good tone among the endings', () => {
  const { container, rerender } = render(<EntityStatus status="queue_empty" />)
  expect(container.querySelector('.ent-status')).toHaveClass('ent-status-good')

  rerender(<EntityStatus status="budget_exhausted" />)
  expect(container.querySelector('.ent-status')).not.toHaveClass('ent-status-good')
})

it('renders an unknown status plainly rather than alarmingly', () => {
  const { container } = render(<EntityStatus status="from_a_newer_backend" />)
  const chip = container.querySelector('.ent-status')
  expect(chip).toHaveClass('ent-status-neutral')
  expect(chip?.textContent).toBe('from a newer backend')
})

it('shows a reason as text rather than as a title attribute', () => {
  render(<EntityStatus status="failed" detail="model returned no content" />)

  // `title` is not keyboard-reachable, not available on touch and
  // inconsistently announced — the defect S-D3 counts nine instances of, and
  // which `DispatchChip` uses today to carry a failure's reason.
  expect(screen.getByText('model returned no content')).toBeVisible()
})
