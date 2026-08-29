import { render } from 'vitest-browser-react'
import { beforeEach, expect, it, vi } from 'vitest'

import { notify, useToasts } from '@application/notifications/toast-store.ts'

import { Toasts } from './Toasts.tsx'

/** B144: a toast made the material tab strip unclickable.
 *
 * The measurement, from the entry: `.toasts` was `position: fixed; top:
 * calc(var(--topbar-h) + 10px)`, putting the first toast at y=54;
 * `ProjectView`'s tab strip spans y=44-66; `.toast` sets `pointer-events:
 * auto`. So a toast always landed on the strip and swallowed the click.
 *
 * A hit test rather than a rect comparison, and that is CLAUDE.md's "check
 * pixels, not the DOM": the tabs had the right size, the right colour and the
 * right text throughout, and were simply underneath something. Two boxes that
 * overlap and two that do not are indistinguishable from
 * `getBoundingClientRect` unless you do the arithmetic yourself, and
 * `elementFromPoint` is the browser doing it with the same rules the click
 * used.
 *
 * jsdom cannot run any of this: it lays nothing out, `getBoundingClientRect`
 * is a zero rect on every element, and `elementFromPoint` answers `null`
 * regardless. This is the reason the file is `.browser.test.tsx`.
 */

/** A stand-in for the project page's tab strip, at the y band the entry
 *  measured. Not `ProjectView` itself: mounting it needs a container, a query
 *  client, a router and six repositories, none of which affects where a
 *  `position: fixed` stack lands. What matters is that something occupies
 *  y=44-66 across the full width and can be hit-tested. */
const STRIP_TOP = 44
const STRIP_HEIGHT = 22

const Strip = () => (
  <div
    data-testid="strip"
    style={{
      position: 'fixed',
      top: `${STRIP_TOP}px`,
      left: 0,
      right: 0,
      height: `${STRIP_HEIGHT}px`,
    }}
  />
)

beforeEach(() => {
  useToasts.setState({ toasts: [] })
})

it('leaves the tab strip clickable while a toast is up', async () => {
  await render(
    <>
      <Strip />
      <Toasts />
    </>,
  )
  notify('extraction queued', 'good')
  // The store is outside React, so the stack is not in the document until
  // the subscription has re-rendered it.
  await vi.waitFor(() => expect(document.querySelector('.toast')).not.toBeNull())

  // The right-hand end of the strip, where the stack used to land. A single
  // point rather than every tab's centre: the stack is right-aligned, so the
  // rightmost point of the band is the worst case, and if that one is the
  // strip then no point further left is a toast.
  const hit = document.elementFromPoint(
    window.innerWidth - 20,
    STRIP_TOP + STRIP_HEIGHT / 2,
  ) as HTMLElement | null

  // Proved red by restoring `top: calc(var(--topbar-h) + 10px)` on `.toasts`
  // in `states.css`: the hit is the toast's message element and this fails.
  expect(hit?.closest('.toasts')).toBeNull()
  expect(hit?.dataset.testid).toBe('strip')
})

it('puts the stack below the strip rather than merely narrower than it', async () => {
  await render(
    <>
      <Strip />
      <Toasts />
    </>,
  )
  notify('extraction queued', 'good')
  await vi.waitFor(() => expect(document.querySelector('.toast')).not.toBeNull())

  const stack = document.querySelector('.toasts') as HTMLElement
  const box = stack.getBoundingClientRect()

  // The rect, as a second reading of the same fact: a stack moved sideways
  // would pass the hit test above at the point sampled and still collide with
  // a wider strip on another route.
  expect(box.top).toBeGreaterThan(STRIP_TOP + STRIP_HEIGHT)
})
