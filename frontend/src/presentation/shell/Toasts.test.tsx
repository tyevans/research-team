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

/** The second half: reachable, and survivable to leave.
 *
 * The close button closed L-F37 but left two holes either side of it. A toast
 * raised while the reader is deep in the timeline is a fixed column at the end
 * of the document, so the only route to it is Tab through the entire page --
 * an affordance you can only reach by giving up your place is one most people
 * will not use. And pressing Enter on it dropped focus to `<body>`, so the
 * price of dismissing a notification was your place in the page anyway.
 *
 * F6 is the ARIA-practices key for cycling to a notification region and the
 * one Radix chose; nothing else in this console binds it (Escape is taken
 * three times over, `/` once). The listener exists only while a toast does,
 * which is what keeps the browser's own F6 intact the rest of the time.
 */

it('names the region, so arriving in it says where you are', () => {
  act(() => {
    notify('saved', 'good')
  })
  render(<Toasts />)

  // Without the name, F6 lands the reader in an unnamed `div` and a screen
  // reader announces the button and nothing about the place it is in. The
  // landmark is also what makes F6 *conventional* rather than merely bound.
  expect(screen.getByRole('region', { name: 'Notifications' })).toBeInTheDocument()
})

it('brings focus to the stack from anywhere in the page', async () => {
  const user = userEvent.setup()
  act(() => {
    notify('could not reach the server', 'bad')
  })
  render(
    <>
      <button type="button">somewhere in the page</button>
      <Toasts />
    </>,
  )

  await user.click(screen.getByRole('button', { name: 'somewhere in the page' }))
  await user.keyboard('{F6}')

  // The oldest toast, not the newest: the stack reads top-down and the top is
  // where a reader starts.
  expect(screen.getByRole('button', { name: 'Dismiss: could not reach the server' })).toHaveFocus()
})

it('leaves F6 to the browser when there is nothing to reach', async () => {
  const user = userEvent.setup()
  render(
    <>
      <button type="button">somewhere in the page</button>
      <Toasts />
    </>,
  )
  const elsewhere = screen.getByRole('button', { name: 'somewhere in the page' })
  await user.click(elsewhere)
  await user.keyboard('{F6}')

  // **This passes with the change reverted**, and is here anyway: it is the
  // guard on the part of the design that is not visible in the code, which is
  // that F6 keeps its browser meaning (pane cycling in Chrome and Firefox)
  // every moment the console has nothing to say. An empty stack registers no
  // listener at all, so there is nothing to consume the key.
  expect(elsewhere).toHaveFocus()
})

it('hands focus to the next toast when one is dismissed', async () => {
  const user = userEvent.setup()
  act(() => {
    notify('saved', 'good')
    notify('could not reach the server', 'bad')
  })
  render(<Toasts />)

  await user.tab()
  await user.keyboard('{Enter}')

  // Rejected: returning to the page after each dismissal, which makes clearing
  // three toasts three round trips. The stack is frozen while focus is in it,
  // so the next toast is guaranteed to still be there to receive this.
  expect(screen.getByRole('button', { name: 'Dismiss: could not reach the server' })).toHaveFocus()
})

it('hands focus to the previous toast when the last one is dismissed', async () => {
  const user = userEvent.setup()
  act(() => {
    notify('saved', 'good')
    notify('could not reach the server', 'bad')
  })
  render(<Toasts />)

  await user.tab()
  await user.tab()
  await user.keyboard('{Enter}')

  expect(screen.getByRole('button', { name: 'Dismiss: saved' })).toHaveFocus()
})

it('returns the reader to where they came from when the stack empties', async () => {
  const user = userEvent.setup()
  act(() => {
    notify('saved', 'good')
  })
  render(
    <>
      <button type="button">somewhere in the page</button>
      <Toasts />
    </>,
  )

  const elsewhere = screen.getByRole('button', { name: 'somewhere in the page' })
  await user.click(elsewhere)
  await user.keyboard('{F6}')
  // Asserted before the dismissal, and not as reassurance: without it the case
  // is vacuous under a revert, because focus never leaves this button and
  // `{Enter}` merely presses it again.
  expect(screen.getByRole('button', { name: 'Dismiss: saved' })).toHaveFocus()
  await user.keyboard('{Enter}')

  // The whole point of the hotkey: a detour you can come back from. Recorded
  // on entry to the region rather than in the F6 handler, so a reader who
  // arrived by Tab is returned the same way.
  expect(elsewhere).toHaveFocus()
})

it('unfreezes the stack when the last toast is dismissed from the keyboard', async () => {
  const user = userEvent.setup()
  act(() => {
    notify('saved', 'good')
  })
  render(
    <>
      <button type="button">somewhere in the page</button>
      <Toasts />
    </>,
  )

  const elsewhere = screen.getByRole('button', { name: 'somewhere in the page' })
  await user.click(elsewhere)
  // Entered by Tab rather than F6, which is the other half of the claim: the
  // return target is recorded on entry to the region, so it does not matter
  // which way the reader got in.
  await user.tab()
  await user.keyboard('{Enter}')
  expect(elsewhere).toHaveFocus()

  // A latent bug the focus restore closes rather than sets out to fix.
  // Removing a focused element from the DOM fires no `blur` in any browser, so
  // the toast that unmounts under the reader's focus never releases its hold
  // -- and `tick` returns early forever after. Every later toast in the
  // session becomes immortal. Moving focus *before* the unmount is what makes
  // the release happen at all.
  expect(useToasts.getState().holds).toBe(0)

  act(() => {
    notify('and another', 'good')
  })
  step(4_000)
  expect(screen.queryByText('and another')).not.toBeInTheDocument()
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
