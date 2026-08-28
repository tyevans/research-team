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
  heading,
  label,
  actions,
  onClose,
  flush = false,
  children,
}: {
  /** Rendered as the drawer's heading. Named `heading` and not `title`: see
   *  `primitives.tsx`, where the same rename is argued for the same reason. */
  heading: ReactNode
  /** The accessible name, as plain text. Separate from `heading` because a
   *  heading may carry markup, and `aria-label` takes a string. */
  label: string
  /** Controls sitting beside the close button -- a link out, usually. */
  actions?: ReactNode
  onClose: () => void
  /** The body pads its own content, and this turns that off for a caller that
   *  brings its own -- a scroller with its own inset, prose with its own
   *  measure.
   *
   * The default is the fix rather than the flag. Padding used to be every
   * caller's job, stated in a comment beside `.confirm` in `tree.css`, and
   * `.confirm` has that comment because it shipped without any: the paragraphs
   * sat against the drawer's border and the confirm button landed on the last
   * pixel column. The topic manage panel was the same omission a second time,
   * back when it was a `Drawer` -- it is `TopicManagePane`, a plain region
   * with its own utilities, and no caller of this component since slice 3b --
   * and every `Drawer` in the workbench is a third. A convention nobody can see
   * they have broken gets broken; forgetting `flush` now costs a double inset,
   * which is visible and mild, rather than text against a border.
   *
   * Named for what it does to the box, not for who wants it -- `flush` is a
   * property of the edge. `padded={false}` was the alternative and reads as
   * though the drawer is doing less, when the caller is doing more. */
  flush?: boolean
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
      {/* The box is Tailwind utilities rather than `course.css`'s `.drawer*`
          rules, and this is a deletion fix rather than a filing preference.
          `Drawer` is reached from the shell on every route -- `AgentWidget` ->
          `WorkerDrawer` -> `Drawer` -- and is the base of `Confirm`, while
          `course.css` is on the die-with-its-screen list. Deleting that file
          with the course view would have taken `position: fixed`, the
          right-anchored box, the surface, the border, the flex column and the
          body's inset off a dialog that is still on screen, with nothing
          failing: jsdom applies no stylesheet, so no test could see it, and a
          class that resolves to nothing raises no error. Found by
          `docs/reports/stylesheet-orphan-sweep.md` rather than by a failure,
          which is the whole point about it.

          The values are the deleted rules' own, not the nearest scale step:
          `w-[42vw]`, `max-w-[640px]`, `min-w-[360px]` and the 12px/16px insets
          are arbitrary because 42vw, 640, 360, 12 and 16 are not on this
          project's spacing scale (3/6/10/14/20/28). Rounding them would be a
          visual change smuggled into a filing fix.

          **`drawer` stays on the class list and is now a hook rather than a
          rule.** `responsive.css` narrows this panel to full width below 820px
          and is a shared stylesheet that survives the route merge. Keeping the
          name keeps that override -- and it now actually applies: an unlayered
          `.drawer` beats a `@layer utilities` one regardless of order, where
          before it lost outright, because `index.css` imports `responsive.css`
          *above* `course.css` and both selectors were 0-1-0. So a narrow
          viewport gets the full-width drawer it has been asking for since that
          rule was written. That is a behaviour change, at one breakpoint, in
          the direction the rule already stated. */}
      <aside className="drawer fixed inset-y-0 right-0 left-auto flex w-[42vw] max-w-[640px] min-w-[360px] flex-col overflow-hidden border-l border-line bg-bg-panel">
        <header className="flex flex-none items-center gap-[8px] border-b border-line px-[12px] py-3">
          <h3 className="m-0 text-sm font-semibold">{heading}</h3>
          <span className="flex-auto" />
          {actions}
          <button type="button" className="btn btn-sm" ref={closeButtonRef} onClick={onClose}>
            Close
          </button>
        </header>

        {/* The body's inset, carried whole from `course.css` because the
            measurement is the reason for it and would not survive being
            paraphrased. The horizontal 12px is the head's 12px on purpose: the
            heading and the first line under it are read as one column, and 12px
            against 0 put them visibly out of line. Measured in Chromium at
            `layout/OverlayHost` FocusReturnsToTheRow, before the rule existed:
            the body's only child ran from x=743 to x=1280 -- one pixel inside
            the drawer's left border, out to the viewport's last column -- while
            the title above it sat at 755. The vertical rhythm is `.conv`'s,
            which is the largest of the three insets callers used and the one a
            reader sees most.

            `data-flush` rather than the old `is-flush` class: the class was a
            selector `course.css` keyed on, and a class name kept after its rule
            is gone is the `.sub` orphan this same sweep found elsewhere. The
            attribute says the same thing to a test and claims no dressing. */}
        <div
          data-drawer="body"
          data-flush={flush || undefined}
          className={
            flush
              ? 'flex flex-auto flex-col overflow-auto p-0'
              : 'flex flex-auto flex-col overflow-auto px-[12px] pt-3 pb-[16px]'
          }
        >
          {children}
        </div>
      </aside>
    </Overlay>
  )
}
