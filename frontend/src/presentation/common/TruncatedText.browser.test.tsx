import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import type { EntityHead } from '@domain/entity/entity-head.ts'

import { EntityRef } from '../entity/EntityRef.tsx'
import { EntityStatus } from '../entity/EntityStatus.tsx'
import { OverlayHost } from '../layout/OverlayHost.tsx'

/** Whether text is clipped is a measurement, so this is the suite that can
 *  make it.
 *
 * `TruncatedText.test.tsx` holds the negative half — text that fits gains
 * nothing — and can hold no more, because jsdom reports `scrollWidth` and
 * `clientWidth` as 0 on every element, so its unclipped branch is the only
 * one that suite has ever executed. Every assertion below would pass there
 * against a component that did nothing at all.
 *
 * **Proved red twice.** Restoring `max-width: 24ch` to `.ent-status-detail`
 * fails the third test and nothing else, so it is measuring the cap rather
 * than agreeing with the markup. And the first test is what found the real
 * defect in this change: it reported 423 against 200 with no tooltip attached,
 * which is the stale-node oscillation now argued in `TruncatedText.tsx`.
 *
 * `OverlayHost` is mounted because `Tooltip` renders no content without one —
 * a deliberate trade argued in `Tooltip.tsx`, and one this test would
 * otherwise silently fall foul of, since a missing host looks exactly like a
 * tooltip that was never attached.
 */

/** Narrow enough that the text below cannot fit, wide enough that the ellipsis
 *  is doing ordinary work rather than clipping mid-character. */
const RAIL = 200

const LONG = 'does the grant number in the appendix match the one in the abstract'

/** A real call site rather than a bare `TruncatedText`, and that is a finding
 *  rather than a convenience: an inline box has no `scrollWidth` — inline
 *  non-replaced elements ignore `overflow` entirely, and both measurements
 *  come back 0. The truncation only exists because `.ent-ref` is an
 *  `inline-flex` and makes its children flex items, so a test that mounted the
 *  component alone would be measuring a thing the console never renders. */
const head: EntityHead = { kind: 'topic', id: '3f2a1b9c-dead-beef-0000-000000000000', label: LONG }

const Rail = ({ children }: { children: React.ReactNode }) => (
  <OverlayHost>
    <div style={{ width: `${RAIL}px`, display: 'flex' }}>{children}</div>
  </OverlayHost>
)

it('makes clipped text reachable and readable', async () => {
  await render(
    <Rail>
      <EntityRef head={head} />
    </Rail>,
  )

  const text = page.getByText(LONG, { exact: true })
  await expect.element(text).toBeVisible()
  const element = text.element()

  // The precondition, asserted rather than assumed: if the stylesheet stopped
  // truncating, everything below would still pass for the wrong reason.
  expect(element.scrollWidth).toBeGreaterThan(element.clientWidth + 1)

  // Re-queried rather than reusing `element`, and the reason is a real
  // property of the component: attaching the tooltip changes the element's
  // parents, so React mounts a new span and the one measured above is by then
  // detached. Asserting against the stale node reports `tabindex` null and
  // reads exactly like the feature not working.
  const trigger = page.getByText(LONG, { exact: true }).element()

  // `tabIndex` is the whole of "reachable by keyboard": `Tooltip`'s own
  // docstring names `asChild` over a `<span>` as the way to ship a tooltip
  // only a mouse can reach, and this is the line that declines to.
  expect(trigger).toHaveAttribute('tabindex', '0')

  // And that focus actually opens it, which is the claim `tabIndex` only makes
  // possible. `focus()` rather than a keypress on purpose — the arrow-key
  // finding in `Tabs.browser.test.tsx` characterises this harness's key
  // delivery as unreliable, and this test needs the focus event, not a Tab.
  trigger.focus()
  await expect.element(page.getByRole('tooltip')).toHaveTextContent(LONG)
})

it('leaves text that fits alone', async () => {
  await render(
    <OverlayHost>
      <div style={{ width: '900px', display: 'flex' }}>
        <EntityRef head={head} />
      </div>
    </OverlayHost>,
  )

  const element = page.getByText(LONG, { exact: true }).element()
  expect(element.scrollWidth).toBeLessThanOrEqual(element.clientWidth + 1)
  expect(element).not.toHaveAttribute('tabindex')
})

it('gives a status detail the width the row can spare', async () => {
  // The defect, exactly: `.ent-status-detail` capped itself at `24ch` and
  // clipped "model returned no content" with a thousand pixels free beside it.
  // A fixed cap answers "how much is too much" without asking how much there
  // is, and no jsdom test can see the difference — the markup is identical.
  const detail = 'model returned no content'
  await render(
    <OverlayHost>
      <div style={{ width: '900px' }}>
        <EntityStatus status="failed" detail={detail} />
      </div>
    </OverlayHost>,
  )

  const element = page.getByText(detail, { exact: true }).element()
  expect(element.scrollWidth).toBeLessThanOrEqual(element.clientWidth + 1)
})

it('shrinks the reason rather than the status when the row is narrow', async () => {
  // Which part gives way is the layout policy, and it was decided by accident
  // before `.ent-status-label` existed: a bare text node is an anonymous flex
  // item, takes the default `flex: 0 1 auto`, and shrank the status itself —
  // the chip's identity and the thing the tone is about.
  const detail = 'model returned no content'
  await render(
    <Rail>
      <EntityStatus status="budget_exhausted" detail={detail} />
    </Rail>,
  )

  const label = page.getByText('budget exhausted', { exact: true }).element()
  expect(label.scrollWidth).toBeLessThanOrEqual(label.clientWidth + 1)

  const reason = page.getByText(detail, { exact: true }).element()
  expect(reason.scrollWidth).toBeGreaterThan(reason.clientWidth + 1)
})
