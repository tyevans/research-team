import clsx from 'clsx'

import { useToasts } from '@application/notifications/toast-store.ts'

export const Toasts = () => {
  const toasts = useToasts((state) => state.toasts)

  return (
    <div id="toasts" className="toasts" aria-live="polite">
      {/* The one suppression here that is hiding a real defect rather than a
          misread pattern, so it is worth being exact about.

          A toast can be dismissed by clicking it and by no other means: there
          is no close button and no key handler, which is a keyboard user with
          no route at all. The component-system spec calls this L-F37 and
          routes it to phase 4, where `Toast` becomes a Radix primitive with a
          real close affordance.

          What was considered and rejected for phase 0: `role="button"` plus a
          `tabIndex` and an Enter/Space handler, the same shape used on
          `FileHistory`'s revision header in this commit. It is rejected here
          because this div sits inside `aria-live="polite"`, and giving it a
          button role changes what is *announced* -- a screen reader prefixes
          the role, so "saved" becomes "button, saved" on every notification
          the console raises. Trading a worse announcement for a tab stop on an
          element that disappears on a timer is not obviously a gain, and a
          half-fix here would also have to be undone in phase 4.

          So this is deliberately left broken, visibly, rather than papered
          over. If phase 4 slips, this comment is the record that the defect
          was known and priced. */}
      {toasts.map((toast) => (
        // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
        <div
          key={toast.id}
          className={clsx('toast', toast.tone !== 'neutral' && toast.tone)}
          onClick={() => useToasts.getState().dismiss(toast.id)}
        >
          {toast.message}
        </div>
      ))}
    </div>
  )
}
