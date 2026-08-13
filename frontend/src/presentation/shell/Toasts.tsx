import clsx from 'clsx'
import { useEffect, useRef } from 'react'

import { useToasts } from '@application/notifications/toast-store.ts'

/** The notification stack, with a way out of it that is not the mouse.
 *
 * **L-F37, closed.** A toast used to be dismissable by clicking it and by no
 * other means: no close button, no key handler, so a keyboard user had no
 * route at all and simply waited. The previous version of this file said so in
 * a comment and left the defect visible rather than papering over it, and
 * routed the fix here.
 *
 * What that comment ruled out is still ruled out, and for the reason it gave:
 * `role="button"` on the toast itself would sit inside `aria-live="polite"`,
 * and a screen reader prefixes the role, so every notification the console
 * raises would be announced as "button, saved". The fix is a real `<button>`
 * *inside* the toast instead. The message announces as prose, the control has
 * its own accessible name, and neither borrows the other's semantics.
 *
 * **Clicking anywhere on the toast no longer dismisses it**, and that is a
 * deliberate loss. Keeping it would have meant keeping a `div` with an
 * `onClick` and no key handler -- the exact thing the suppression was hiding
 * -- so the choice was a lint suppression that outlives its defect or one
 * fewer mouse affordance. Every mainstream toast implementation lands the same
 * way, and the close button is a larger target than most of them give it.
 *
 * **A control you can only reach by giving up your place is one nobody uses.**
 * That was what the close button still left: the stack is a fixed column at
 * the end of the document, so a reader working in the timeline reached it by
 * tabbing the whole page, and dismissing it dropped focus to `<body>` --
 * paying for the notification with their position either way. F6 in and a
 * restore out are the two halves of the fix, and both are ~20 lines, which is
 * why the spec's proposal to adopt Radix `react-toast` for them was declined:
 * +3.2 kB gzipped and a rewrite of every argued decision above, to buy these
 * two plus swipe-to-dismiss on a localhost desktop console.
 */
export const Toasts = () => {
  const toasts = useToasts((state) => state.toasts)
  const region = useRef<HTMLDivElement>(null)

  // Where the reader was standing when they came in here. Recorded on entry
  // to the region rather than in the F6 handler, so arriving by Tab is
  // returned from the same way -- one mechanism, two doors.
  const cameFrom = useRef<HTMLElement | null>(null)

  // F6, and only while there is something to reach.
  //
  // The key itself is the ARIA-practices convention for cycling to a
  // notification region and the one Radix binds; nothing in this console binds
  // it today (Escape three times over, `/` once in the tree, arrows and Enter
  // inside widgets that own their own focus).
  //
  // The gate is the part worth defending. A `window` listener is exactly what
  // made Escape a mess here -- two owners, one keypress, "one Escape folds
  // twice" -- so this one earns its place by being unlike that in two ways.
  // There is only ever one notification region, so the multiple-owner problem
  // it caused cannot arise; and the listener is registered only while a toast
  // exists, so F6 keeps its browser meaning (pane cycling in Chrome and
  // Firefox) every moment the console has nothing to say, which is nearly all
  // of them. That is also why it is here rather than in `OverlayHost`: the
  // host arbitrates Escape between competing layers, and this competes with
  // nobody. The toast stack is deliberately outside the host anyway, argued
  // where `--z-toast` is declared.
  useEffect(() => {
    if (toasts.length === 0) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'F6') return
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return
      const host = region.current
      // Already inside: the key goes back to the browser rather than being
      // swallowed into a no-op, so a second press still cycles out of the page
      // the way it does everywhere else.
      if (!host || host.contains(document.activeElement)) return
      const first = host.querySelector('button')
      if (first === null) return
      event.preventDefault()
      first.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [toasts.length])

  // Hold the stack while a pointer is over a toast or focus is inside one.
  // Without this the close button is unreliable in exactly the case it exists
  // for: a keyboard user tabbing towards a toast is racing a timer they cannot
  // see, and a reader who moved the mouse across to read a long error watches
  // it leave anyway.
  //
  // On each toast rather than on the region, because `.toasts` is
  // `pointer-events: none` -- it is a full-height fixed column and would
  // otherwise swallow clicks meant for the page underneath. Only the toasts
  // themselves are `pointer-events: auto`, so they are the only elements a
  // pointer can be said to be over.
  // Wrapped rather than destructured off `getState()`. Two reasons, and the
  // lint rule (`@typescript-eslint/unbound-method`) only names the first:
  // plucking a method off an object drops its receiver, and reading the store
  // at render time captures whatever it held then, which is exactly the bug
  // this component is fixing in the timer.
  const hold = () => useToasts.getState().hold()
  const release = () => useToasts.getState().release()

  const onFocus = (event: React.FocusEvent<HTMLDivElement>) => {
    hold()
    const from = event.relatedTarget
    // Moves *within* the stack leave the record alone -- tabbing from one
    // toast to the next must not overwrite the way out with a way back in.
    if (from instanceof HTMLElement && region.current?.contains(from)) return
    // Overwritten rather than only set, including with `null`: a stale element
    // from an earlier visit is worse than no target, because focus would jump
    // somewhere the reader has not been in minutes.
    cameFrom.current = from instanceof HTMLElement ? from : null
  }

  /** Dismiss, and put focus somewhere that is not `<body>`.
   *
   * Next toast, then previous, then back out to where the reader came in.
   *
   * Rejected: going straight back out every time. It reads well for one toast
   * and badly for three -- clearing a stack becomes three round trips through
   * F6 -- and the stack is at its longest exactly when something has gone
   * wrong, which is when the reader least wants the extra work. Rejected the
   * other way round too (previous before next): the column is chronological
   * top-down, so "next" is where the eye already is.
   *
   * The next toast is guaranteed to still be there to receive focus: `tick`
   * returns early while anything holds, and focus inside any toast holds the
   * whole stack, so nothing expires under the reader while they are in here.
   * That is a complete answer rather than a narrowed window -- the check is
   * synchronous and the sweeper cannot interleave with an event handler -- and
   * it is only complete because the hold is a store-wide counter rather than
   * per toast.
   *
   * Focus moves *before* the unmount, which also closes a bug that was already
   * here: removing a focused element from the DOM fires no `blur` in any
   * browser, so the toast that vanished under the reader's focus never
   * released its hold and every later toast in the session was immortal.
   *
   * A mouse click runs this too, since clicking a button focuses it. Left
   * unbranched: moving focus to a sibling close button draws nothing for a
   * pointer user (`:focus-visible`), and a modality check to avoid a no-op is
   * more machinery than the thing it guards.
   */
  const dismiss = (id: number, button: HTMLButtonElement) => {
    const toast = button.closest('.toast')
    const nextInStack = toast?.nextElementSibling ?? toast?.previousElementSibling ?? null
    const target = nextInStack?.querySelector('button') ?? cameFrom.current
    // Only if it is still in the page: the reader's origin can have been
    // unmounted by a route change while they were reading the notification.
    if (target !== null && target.isConnected) target.focus()
    useToasts.getState().dismiss(id)
  }

  return (
    <div
      id="toasts"
      className="toasts"
      // A landmark with a name, which is what makes the hotkey coherent: land
      // somewhere and that somewhere should say what it is. Today a reader
      // arriving hears the button's name and nothing about the place. The
      // name does not leak into the announcements -- it is on the container,
      // not on a child inside the live region, which is the distinction that
      // ruled out `role="button"` on the toast above.
      //
      // Present even when empty, so the landmark list carries one dead entry.
      // The alternative is worse: a live region has to be in the DOM before
      // content is inserted into it or the insertion is not announced at all.
      role="region"
      aria-label="Notifications"
      aria-live="polite"
      ref={region}
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={clsx('toast', toast.tone !== 'neutral' && toast.tone)}
          onMouseEnter={hold}
          onMouseLeave={release}
          // `onFocus`/`onBlur` rather than the capture variants: React's
          // versions of these bubble, so focus landing on the button inside
          // reaches this element. The native events do not, which is the one
          // place React's synthetic behaviour is what you want here.
          onFocus={onFocus}
          onBlur={release}
        >
          <span className="toast-message">{toast.message}</span>
          <button
            type="button"
            className="toast-close"
            // Named for what it does to *this* toast rather than "Close",
            // because a screen reader user arriving here by Tab has several
            // and no visual grouping to tell them apart.
            aria-label={`Dismiss: ${toast.message}`}
            onClick={(event) => dismiss(toast.id, event.currentTarget)}
          >
            {/* Decorative: the accessible name is on the button. */}
            <span aria-hidden="true">×</span>
          </button>
        </div>
      ))}
    </div>
  )
}
