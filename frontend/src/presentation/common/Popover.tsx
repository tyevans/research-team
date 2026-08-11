import * as PopoverPrimitive from '@radix-ui/react-popover'
import type { ReactNode } from 'react'

import { useLayer } from '../layout/OverlayHost.tsx'

/** A panel hung off a control, with the page still live behind it.
 *
 * **The same bridge as `Tooltip`, and that is the finding rather than the
 * feature.** Three parts, unchanged: portal into the host's own container so
 * the content shares `--z-overlay` and needs no `z-index`; `useLayer({modal:
 * false})` while open so the host orders it against everything else that is
 * open; and `onEscapeKeyDown={(event) => event.preventDefault()}`, which is
 * Radix's documented seam -- `DismissableLayer` dismisses only `if
 * (!event.defaultPrevented)`, so the keypress carries on to the host's
 * `window` listener and the host decides who owns it. No `stopPropagation`
 * anywhere; the key is declined at the library's boundary, not intercepted
 * downstream.
 *
 * That the bridge transferred verbatim from a tooltip to a popover is worth
 * recording, because it was not obvious: a tooltip never takes focus and a
 * popover does, so Radix's `FocusScope` is live here and the host's `inert`
 * is not (`modal: false`). The two turned out not to interact at all --
 * `gives Escape to the drawer in front, and leaves the popover open` is the
 * test that would fail if they did.
 *
 * **What this replaces at its one call site**, which is the reason it exists
 * rather than a general-purpose wish: `AgentWidget` was an `Overlay` with an
 * `anchor` prop, a `useEffect` that reached into the panel with
 * `querySelector('button')` to move focus, a `close()` that put focus back on
 * the toggle by hand, `aria-expanded`/`aria-controls` written out, and a
 * stylesheet rule that pinned the panel to the viewport with `position:
 * fixed; top: var(--topbar-h)` because the host offers no anchoring. Radix
 * supplies all five: anchoring that measures the trigger and flips off a
 * viewport edge, a focus scope that moves focus in and gives it back, and the
 * ARIA wiring between trigger and content.
 *
 * **What is deliberately *not* here: `modal`.** Radix's `Popover` has a modal
 * mode that applies `aria-hidden` and pointer-blocking to the rest of the
 * page. That is a second implementation of what `OverlayHost` does with
 * `inert`, deciding from Radix's stack rather than the host's -- the exact
 * two-authorities problem this bridge exists to remove. A layer that wants the
 * page is a `Drawer`.
 *
 * The cost, the same one `Tooltip` pays: with no `OverlayHost` in scope the
 * content renders as nothing at all. A story or test that mounts a `Popover`
 * bare shows a trigger that opens nothing. Mount a `Shell`, or an
 * `OverlayHost`.
 */
export const Popover = ({
  open,
  onOpenChange,
  label,
  trigger,
  className,
  align = 'end',
  sideOffset = 6,
  children,
}: {
  open: boolean
  /** Controlled, not `defaultOpen`. Every popover in this console remembers
   *  its state somewhere the component does not own -- the agent dock puts it
   *  in `PreferenceStore` -- and a primitive with internal state would have to
   *  be talked out of it at each call site. */
  onOpenChange: (open: boolean) => void
  /** The accessible name of the panel, as plain text. Required for the same
   *  reason `Overlay` requires one: Radix gives the content `role="dialog"`,
   *  and an unnamed dialog is announced as "dialog" and nothing else. */
  label: string
  /** The control the panel hangs off. Rendered with `asChild`, so it must be a
   *  single already-focusable element that forwards a `ref` -- a real
   *  `<button>`. Radix puts `aria-expanded`, `aria-controls` and
   *  `aria-haspopup` on it, so a call site writing those itself is writing
   *  them twice. */
  trigger: ReactNode
  /** Classes for the panel itself. The box is the caller's -- this component
   *  owns placement and dismissal and has no opinion about how a panel looks,
   *  which is what lets the dock keep its own border and shadow. */
  className?: string
  align?: 'start' | 'center' | 'end'
  /** Gap between trigger and panel. `0` for a panel that reads as hanging off
   *  the edge it opened from, which is what the agent dock wants under the
   *  topbar; the default leaves the panel visibly detached. */
  sideOffset?: number
  children: ReactNode
}) => (
  <PopoverPrimitive.Root open={open} onOpenChange={onOpenChange}>
    <PopoverPrimitive.Trigger asChild>{trigger}</PopoverPrimitive.Trigger>
    {/* Mounted only while open, for the reason argued in `Tooltip`: `useLayer`
        inside the content is what makes "registered with the host" and "open"
        the same fact. Radix's `Presence` would hold the subtree through an
        exit animation and therefore hold the layer -- a layer owning Escape
        for something already invisible. */}
    {open ? (
      <PopoverLayer
        label={label}
        className={className}
        align={align}
        sideOffset={sideOffset}
        onDismiss={() => onOpenChange(false)}
      >
        {children}
      </PopoverLayer>
    ) : null}
  </PopoverPrimitive.Root>
)

/** The floating half, and the only place the two dismissal stacks meet.
 *
 * Separate from `Popover` because `useLayer` must run exactly while the
 * popover is open and a hook cannot be conditional. Mounting the component
 * conditionally is the same statement in a form React accepts.
 */
const PopoverLayer = ({
  label,
  className,
  align,
  sideOffset,
  onDismiss,
  children,
}: {
  label: string
  className: string | undefined
  align: 'start' | 'center' | 'end'
  sideOffset: number
  onDismiss: () => void
  children: ReactNode
}) => {
  // `onDismiss` closes the popover and nothing else -- routed through the host
  // so that the *host* decides whether this popover is the top layer. Radix
  // would decide against its own stack, in which a `Drawer` does not appear at
  // all.
  //
  // Closing by prop rather than through Radix's own dismissal does not cost
  // the focus return: Radix's `FocusScope` restores on unmount whatever caused
  // it, so Escape still lands the reader back on the trigger. Asserted rather
  // than assumed -- `gives Escape back to the trigger` in `Popover.test.tsx`
  // is what fails if a Radix upgrade moves that restore onto its own close
  // path.
  //
  // `returnFocus` is `undefined` because the host pays focus debts only for
  // modal layers, and a popover is deliberately not one.
  //
  // **A modal above this makes it inert, and forgetting it was a real
  // regression rather than a theoretical one.** A Radix layer is portalled
  // straight into the container with no `.lay-layer` around it, so it gets none
  // of what `Overlay` marks; `blocked` is the host's own answer to "is a modal
  // in front of me", and applying it here is all this component owes. What it
  // means, why the attributes come in pairs, and how it was found are argued
  // once beside `blocked` in `useLayer`.
  const { container, blocked } = useLayer({ modal: false, onDismiss, returnFocus: undefined })

  // No host, no content -- the trade argued above `Popover`.
  if (!container) return null

  return (
    <PopoverPrimitive.Portal container={container}>
      <PopoverPrimitive.Content
        aria-label={label}
        inert={blocked}
        aria-hidden={blocked ? true : undefined}
        align={align}
        sideOffset={sideOffset}
        // Radix's documented seam for declining a dismissal, and the whole
        // bridge in one line. Not `stopPropagation`: the event must still
        // reach the host's `window` listener, which is the thing that decides
        // who owns this keypress.
        onEscapeKeyDown={(event) => event.preventDefault()}
        // **A fourth part of the bridge that `Tooltip` did not need, found by
        // a red test rather than reasoned.** Radix dismisses a non-modal
        // popover when focus leaves it, which is right for a popover that
        // nothing is in front of and wrong for the one arrangement this whole
        // exercise is about: a modal `Drawer` opening moves focus to its Close
        // button, so the popover behind it closed on focus-out before Escape
        // was ever pressed. `gives Escape to the drawer in front, and leaves
        // the popover open` failed exactly there, with the panel already gone
        // from the document.
        //
        // That is also the dock's real flow rather than a contrivance:
        // pressing a row opens a worker drawer, and the dock underneath used
        // to stay open. Declining focus-outside keeps it open, so the reader
        // closing the drawer is back where they were.
        //
        // The cost, plainly: Tab out of the last thing in the panel leaves the
        // panel open behind the reader. Escape and a press outside both still
        // dismiss it, and a popover with a way in but no way out would be
        // worse -- but this is the trade, and a `Menu` (which cycles focus
        // within itself) is the primitive that does not have to make it.
        onFocusOutside={(event) => event.preventDefault()}
        // `pointer-events-auto` because `.lay-overlay-host` is `inset: 0` with
        // `pointer-events: none` and each layer turns them back on for itself,
        // the same thing `.lay-layer` does for an `Overlay`. Said as a utility
        // rather than a rule because this element is Radix's, not ours.
        className={className ? `pointer-events-auto ${className}` : 'pointer-events-auto'}
      >
        {children}
      </PopoverPrimitive.Content>
    </PopoverPrimitive.Portal>
  )
}
