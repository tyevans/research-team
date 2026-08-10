import { useCallback, useRef, type ReactNode } from 'react'

import { Overlay } from '../layout/OverlayHost.tsx'

/** A panel read over the page, with the page still behind it.
 *
 * Extracted from `WorkerDrawer`, which owned this shell alone until the
 * document reader needed the same one. What is shared is not the box -- that
 * is nine lines of CSS -- but the keyboard contract: focus moves in on open
 * and returns on close, Escape closes, and Tab cannot walk out into the page
 * behind. A second copy of that is how one of two dialogs quietly stops
 * trapping focus a year later.
 *
 * **What this file no longer does, and why that is the point.** It used to
 * render its own `.drawer-backdrop` at `z-index: 20`, own a `window` keydown
 * listener for Escape, and hand-roll a Tab trap over a `FOCUSABLE_SELECTOR`
 * re-queried on every keypress. All three are deleted; `Overlay` supplies
 * them, and supplies them better:
 *
 * - The trap was a *simulation* of confinement -- it cycled Tab within the
 *   `aside` and could only ever cover the keys it saw. It did nothing about
 *   the pointer beyond the backdrop, nothing about a screen reader's virtual
 *   cursor, and nothing about the dock popover painting on top of it at
 *   `z-index: 40`. The host marks the whole page `inert`, which is the
 *   platform doing all three at once and is the reason `Confirm`-over-`Drawer`
 *   now works without either knowing about the other.
 * - Escape on `window` meant two open dialogs both closed on one keypress. The
 *   host gives Escape to the topmost layer only.
 *
 * What stays here is the one thing the host deliberately does not do: **move
 * focus in on open and give it back on close.** `inert` makes everything else
 * unreachable but moves nothing, so without this a reader opening a drawer is
 * confined to it with their focus still on the row outside.
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
  /** Where focus was before this drawer took it, to give back on close.
   *
   * Captured in the callback ref below rather than in an effect, and the
   * ordering is the whole reason. React runs callback refs during commit and
   * effects after it, so by the time an effect could read
   * `document.activeElement` the ref has already moved focus onto the close
   * button — an effect capturing there records the drawer's own button as
   * "where the reader came from", and closing the drawer restores focus to a
   * node that has just been removed. That is exactly what happened when these
   * two responsibilities were first split apart, and `gives focus back to the
   * element that opened it` is the test that caught it. */
  const previouslyFocused = useRef<Element | null>(null)

  // Giving that focus *back* is the host's job, not this component's, and the
  // ref above is simply handed over as `returnFocus`. `Drawer` did own the
  // restore, in an unmount cleanup, and it was broken in a browser while every
  // test in this repository stayed green: the cleanup runs while the page is
  // still `inert`, and focusing into an inert subtree does nothing, so the
  // reader was dropped on `<body>`. `OverlayHost` carries the measurement and
  // the reasoning; it is the only thing that knows when the page comes back.

  // Move focus in on open. The close button, not the heading, is the target: a
  // heading isn't natively focusable (it would need a `tabIndex={-1}` just to
  // receive focus programmatically, dropping it into the tab order like a fake
  // control), while the close button is already a real, always-present
  // affordance a keyboard user expects to be able to reach immediately.
  // Without this, focus stays on whatever row opened the drawer, so a
  // screen-reader user hears the drawer's content announced without their
  // focus ever having moved into it.
  //
  // **A callback ref rather than the mount effect this used to be**, and the
  // change is not cosmetic. `Overlay` renders `null` until its host's
  // container ref has been set, so on the render where a `Drawer` mounts there
  // is no close button in the document yet; a `useEffect(..., [])` reads
  // `null` off the ref, focuses nothing, and never runs again. That is a real
  // regression and not only a test artifact — it is quiet in the app today
  // only because `Shell` mounts the host long before any drawer opens, so the
  // one arrangement that hits it is a drawer open on first paint. A callback
  // ref fires when the node actually attaches, whenever that is.
  //
  // Guarded so it fires once: a callback ref re-runs whenever React re-attaches
  // the node, and without the guard a re-render mid-read would yank focus off
  // whatever the reader had tabbed to and back onto Close.
  const focused = useRef(false)
  const closeButtonRef = useCallback((node: HTMLButtonElement | null) => {
    if (!node || focused.current) return
    focused.current = true
    previouslyFocused.current = document.activeElement
    node.focus()
  }, [])

  return (
    <Overlay label={label} modal onDismiss={onClose} returnFocus={previouslyFocused}>
      {/* No `role`, no `aria-modal` and no `aria-label` here any more: the
          layer's own content element carries all three, and a dialog nested
          directly inside a dialog announces two. The `onClick` that used to
          stop a click inside the drawer reaching the backdrop is gone with it
          -- the backdrop is the layer's, a sibling rather than an ancestor, so
          a click inside the drawer never reaches it in the first place. */}
      <aside className="drawer">
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
    </Overlay>
  )
}
