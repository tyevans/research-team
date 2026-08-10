import { useEffect, useRef, type ReactNode } from 'react'

/** Descendants a keyboard user can land on, queried fresh on every keypress
 *  rather than cached at mount: a drawer's body can be a live transcript that
 *  grows as frames arrive, so a list captured once would go stale and the
 *  trap would eventually cycle to elements that no longer exist, or miss
 *  ones that just arrived. */
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input, textarea, select, [tabindex]:not([tabindex="-1"])'

/** A panel read over the page, with the page still behind it.
 *
 * Extracted from `WorkerDrawer`, which owned this shell alone until the
 * document reader needed the same one. What is shared is not the box -- that
 * is nine lines of CSS -- but the keyboard contract: focus moves in on open
 * and returns on close, Escape closes, and Tab cannot walk out into the page
 * behind. A second copy of that is how one of two dialogs quietly stops
 * trapping focus a year later.
 *
 * The caller keeps its own content and its own actions. This owns only the
 * behaviour that must not vary between two dialogs in the same console.
 */
export const Drawer = ({
  title,
  label,
  actions,
  onClose,
  children,
}: {
  /** Rendered as the drawer's heading. */
  title: ReactNode
  /** The accessible name, as plain text. Separate from `title` because a
   *  heading may carry markup, and `aria-label` takes a string. */
  label: string
  /** Controls sitting beside the close button -- a link out, usually. */
  actions?: ReactNode
  onClose: () => void
  children: ReactNode
}) => {
  const asideRef = useRef<HTMLElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  // Move focus in on open, and give it back on close. The close button, not
  // the heading, is the target: a heading isn't natively focusable (it would
  // need a `tabIndex={-1}` just to receive focus programmatically, dropping
  // it into the tab order like a fake control), while the close button is
  // already a real, always-present affordance a keyboard user expects to be
  // able to reach immediately. Without this, focus stays on whatever row
  // opened the drawer, so a screen-reader user hears the drawer's content
  // announced without their focus ever having moved into it.
  //
  // The element that had focus before opening is captured here rather than
  // assumed, and re-checked for DOM membership before restoring: the row could
  // have been removed while the drawer was open, and focusing a detached node
  // throws in some environments and silently no-ops in others — neither of
  // which puts focus anywhere useful.
  useEffect(() => {
    const previouslyFocused = document.activeElement
    closeButtonRef.current?.focus()
    return () => {
      if (previouslyFocused instanceof HTMLElement && document.contains(previouslyFocused)) {
        previouslyFocused.focus()
      }
    }
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
        return
      }

      // Trap Tab/Shift+Tab inside the drawer so a keyboard user can't tab
      // straight through into the page behind it, which is still rendered and
      // still focusable. Focusable elements are queried here, at keypress
      // time, rather than once at mount — see FOCUSABLE_SELECTOR.
      if (event.key !== 'Tab' || !asideRef.current) return

      const focusable = Array.from(
        asideRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      )
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (!first || !last) return

      const active = document.activeElement
      if (event.shiftKey) {
        if (active === first || !asideRef.current.contains(active)) {
          event.preventDefault()
          last.focus()
        }
      } else if (active === last || !asideRef.current.contains(active)) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    /* A backdrop is not a control, and this one has a keyboard equivalent that
       the rule cannot see: Escape closes the drawer, handled on `window` in the
       effect above and asserted by `Drawer.test.tsx`. What `jsx-a11y` is asking
       for here is a key handler on the backdrop itself, which would be a second
       route to the same behaviour rather than a first route to a missing one.
       Kept as a suppression rather than satisfied, because satisfying it would
       add code that does nothing. Phase 1 removes the question entirely --
       Radix's `Dialog.Overlay` owns dismissal. */
    /* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */
    <div className="drawer-backdrop" onClick={onClose}>
      {/* Not an interaction: the handler exists only to stop a click inside the
          drawer reaching the backdrop and closing what is being read. There is
          no behaviour here for a keyboard user to be excluded from. */}
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions */}
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label={label}
        ref={asideRef}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="drawer-head">
          <h3 className="drawer-title">{title}</h3>
          <span className="drawer-spacer" />
          {actions}
          <button type="button" className="btn btn-sm" ref={closeButtonRef} onClick={onClose}>
            Close
          </button>
        </header>

        <div className="drawer-body">{children}</div>
      </aside>
    </div>
  )
}
