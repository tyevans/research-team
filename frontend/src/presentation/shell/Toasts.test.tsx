import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it } from 'vitest'

import { notify, useToasts } from '@application/notifications/toast-store.ts'

import { Toasts } from './Toasts.tsx'

/** L-F37: a notification a keyboard could not dismiss.
 *
 * Before this, a toast was dismissable by clicking it and by nothing else --
 * no close button, no key handler. `Toasts.tsx` said so in a comment and left
 * the defect visible rather than papering over it, which is why the fix is
 * findable at all.
 *
 * The shape of the fix is constrained by something that comment got right: the
 * toast sits inside `aria-live="polite"`, so putting `role="button"` on it
 * would make a screen reader announce "button, saved" for every notification
 * the console raises. A real `<button>` *inside* the toast keeps the message
 * announcing as prose and gives the control its own name.
 *
 * The half that is easy to leave out is the hold. A close button on a toast
 * that expires on a timer is unreliable in exactly the case it exists for: a
 * keyboard user tabbing towards it is racing a clock they cannot see. Two of
 * the cases below are about the timer *not* running, and they are the ones
 * that would rot silently.
 *
 * **Time is stepped, never waited for.** `tick` is on the store for this
 * reason -- BACKLOG B4 and this session's own work are both about tests whose
 * precondition is a duration, and a toast suite that slept 3.8 seconds would
 * be the same mistake in a new place.
 */

beforeEach(() => {
  // The store is a module singleton, so a toast left up by one case is a toast
  // the next one can see.
  useToasts.setState({ toasts: [], holds: 0 })
})

const step = (ms: number) => act(() => useToasts.getState().tick(ms))

it('gives every toast a control that says which toast it closes', () => {
  act(() => {
    notify('saved', 'good')
    notify('could not reach the server', 'bad')
  })
  render(<Toasts />)

  // Named for the message rather than "Close": a screen-reader user arriving
  // by Tab has several of these and no visual grouping to tell them apart.
  expect(screen.getByRole('button', { name: 'Dismiss: saved' })).toBeInTheDocument()
  expect(
    screen.getByRole('button', { name: 'Dismiss: could not reach the server' }),
  ).toBeInTheDocument()
})

it('dismisses from the keyboard', async () => {
  const user = userEvent.setup()
  act(() => {
    notify('saved', 'good')
  })
  render(<Toasts />)

  await user.tab()
  expect(screen.getByRole('button', { name: 'Dismiss: saved' })).toHaveFocus()
  await user.keyboard('{Enter}')

  // The whole of L-F37. Before this there was no tab stop to reach and no key
  // that did anything; a keyboard user waited the toast out.
  expect(screen.queryByText('saved')).not.toBeInTheDocument()
})

it('does not announce the toast itself as a control', () => {
  act(() => {
    notify('saved', 'good')
  })
  const { container } = render(<Toasts />)

  // The constraint the previous implementation's comment identified, kept as
  // an assertion so the tempting shortcut cannot come back quietly: exactly
  // one button per toast, and it is not the toast.
  expect(container.querySelectorAll('.toast')).toHaveLength(1)
  expect(screen.getAllByRole('button')).toHaveLength(1)
  expect(container.querySelector('.toast')).not.toHaveAttribute('role', 'button')
})

it('expires on its own, with a bad one lasting longer than a good one', () => {
  act(() => {
    notify('saved', 'good')
    notify('could not reach the server', 'bad')
  })
  render(<Toasts />)

  step(3_800)

  // The rule the lifetimes encode: a failure is more likely to be the thing
  // somebody needs to read, and more likely to have arrived while they were
  // looking elsewhere.
  expect(screen.queryByText('saved')).not.toBeInTheDocument()
  expect(screen.getByText('could not reach the server')).toBeInTheDocument()

  step(3_200)
  expect(screen.queryByText('could not reach the server')).not.toBeInTheDocument()
})

it('stops the clock while the pointer is over a toast', async () => {
  const user = userEvent.setup()
  act(() => {
    notify('a long error worth reading', 'bad')
  })
  render(<Toasts />)

  await user.hover(screen.getByText('a long error worth reading'))
  step(20_000)

  // Well past its 7s lifetime. A reader who moved the mouse across to read a
  // long failure and watched it leave anyway has been punished for reading,
  // which is the same complaint as `Conversation`'s scroll latch.
  expect(screen.getByText('a long error worth reading')).toBeInTheDocument()

  await user.unhover(screen.getByText('a long error worth reading'))
  step(7_000)
  expect(screen.queryByText('a long error worth reading')).not.toBeInTheDocument()
})

it('stops the clock while focus is inside a toast', async () => {
  const user = userEvent.setup()
  act(() => {
    notify('saved', 'good')
  })
  render(<Toasts />)

  await user.tab()
  step(20_000)

  // The case the close button exists for. Without the hold, a keyboard user
  // reaching for the control is racing a timer, and the control is gone by the
  // time they arrive -- an affordance that works only if you are fast enough
  // is not an affordance.
  expect(screen.getByRole('button', { name: 'Dismiss: saved' })).toHaveFocus()
  expect(screen.getByText('saved')).toBeInTheDocument()
})

it('keeps holding while any one reason to hold remains', async () => {
  const user = userEvent.setup()
  act(() => {
    notify('saved', 'good')
  })
  render(<Toasts />)

  // Pointer *and* keyboard at once, which is why `holds` is a counter and not
  // a boolean: with a boolean, whichever left first would release both, and
  // the toast would vanish out from under a reader who still had focus in it.
  await user.hover(screen.getByText('saved'))
  await user.tab()
  await user.unhover(screen.getByText('saved'))

  step(20_000)
  expect(screen.getByText('saved')).toBeInTheDocument()
})
