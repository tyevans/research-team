import clsx from 'clsx'

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
 */
export const Toasts = () => {
  const toasts = useToasts((state) => state.toasts)

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

  return (
    <div id="toasts" className="toasts" aria-live="polite">
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
          onFocus={hold}
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
            onClick={() => useToasts.getState().dismiss(toast.id)}
          >
            {/* Decorative: the accessible name is on the button. */}
            <span aria-hidden="true">×</span>
          </button>
        </div>
      ))}
    </div>
  )
}
