import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import clsx from 'clsx'
import { useState, type ReactNode } from 'react'

import { useLayer } from '../layout/OverlayHost.tsx'

/** An explanation attached to a control, reachable by pointer *and* keyboard.
 *
 * **What it replaces.** Roughly twenty `title` attributes carrying real
 * explanations -- "Also autos the workflow review gate, so a run can cross
 * stage boundaries unattended" is a sentence a reader needs before pressing
 * the button, and `title` shows it to a mouse hovering for a second or two and
 * to nobody else. It is not announced on focus, it is unreachable on touch,
 * its delay is the operating system's, and it cannot be styled or read at
 * leisure. Everything below exists because that is the baseline.
 *
 * **What Radix supplies and what it does not.** Positioning (collision
 * flipping against the viewport, the arrow, the anchor measurement) and the
 * ARIA wiring -- `aria-describedby` from trigger to content, `role="tooltip"`,
 * and the pointer/focus timing rules. What it must *not* supply here is
 * dismissal: `@radix-ui/react-dismissable-layer` keeps its own stack of open
 * layers and gives Escape to the topmost of *its* layers, on
 * `document` at capture. `OverlayHost` keeps a different stack and gives
 * Escape to the topmost of *those*. Two stacks, each convinced it is
 * authoritative, is the `GraphDetail` defect exactly -- one keypress closing a
 * panel and the thing in front of it -- arriving as a dependency this time.
 *
 * **The bridge, and why it is three specific things rather than a shrug.**
 *
 * - `useLayer` while open, so the tooltip takes its turn in the host's stack.
 *   Registration is a mount, so a tooltip opened before a drawer sits *under*
 *   it and a drawer opened first sits under the tooltip -- ordering by when
 *   things opened, which is the host's whole mechanism and needs nothing new.
 * - Portalled into the host's own container, so the content shares
 *   `--z-overlay` with every other layer. The alternative, Radix's default
 *   portal to `<body>`, puts the content outside that stacking order and makes
 *   a `z-index` of its own the only way to fix it -- which `check-deleted.mjs`
 *   fails the build over, and which would reintroduce the numbers this host
 *   deleted.
 * - `onEscapeKeyDown={(event) => event.preventDefault()}`. This is Radix's own
 *   documented seam, not a workaround: `DismissableLayer` calls the handler
 *   first and dismisses only `if (!event.defaultPrevented)`. So the key is
 *   *declined* at the library's boundary rather than intercepted somewhere
 *   downstream, and no `stopPropagation` appears anywhere -- the event carries
 *   on to the host's `window` listener untouched, which is what lets the host
 *   decide whether this tooltip is the top layer at all.
 *
 * The cost of the bridge, stated plainly: a tooltip with no `OverlayHost` in
 * scope renders no content at all, exactly as `Overlay` renders `null`. That
 * is a real loss -- `title` worked anywhere -- and it is the same trade the
 * host already made everywhere else, so it is one rule rather than two. A
 * story or test that mounts a `Tooltip` bare will show a trigger and no
 * explanation; mount a `Shell`, or an `OverlayHost`.
 *
 * **The provider is per-tooltip, and that is a deliberate loss.**
 * `TooltipProvider` is where Radix keeps the "skip the delay for the next one"
 * timer, so with one provider per tooltip, moving along a row of chips waits
 * the full delay at each. One provider at the shell would fix that and would
 * also make every `Tooltip` depend on a shell that mounted it -- another
 * ambient requirement beside the host's. Deferred rather than dismissed: if
 * the row-of-chips case starts to matter, the provider goes in `Shell` beside
 * `OverlayHost` and this comment is what says why it moved.
 */
export const Tooltip = ({
  explanation,
  children,
  asChild = false,
  className,
}: {
  /** The sentence a `title` was carrying. Plain text unless there is a reason
   *  -- it is announced through `aria-describedby`, and a screen reader reads
   *  the text content of markup it cannot otherwise convey. */
  explanation: ReactNode
  /** The control being explained. */
  children: ReactNode
  /** Use `children` as the trigger itself rather than wrapping it in a button.
   *
   * Only correct when `children` is a single, already-focusable element that
   * passes a `ref` through -- a real `<a href>` or `<button>`. Anything else
   * (a `<span className="chip">`, the common case here) must take the default,
   * because the wrapper is what puts the trigger in the tab order and a
   * tooltip nobody can focus is the `title` attribute again with extra steps.
   *
   * There is no way for this component to check which it got, so the failure
   * mode is worth naming: `asChild` over a plain `<span>` renders a tooltip
   * that opens on hover and never on focus, and every test here passes. */
  asChild?: boolean
  /** Classes for the wrapper trigger, ignored under `asChild`.
   *
   * Needed because the wrapper is a real element in the layout, not a
   * transparent one: `.run-cell` is a flex child of `.run-cells` and
   * `.agents-row-flat` is a full-width row with a bottom border. Wrapping
   * either in an unclassed `<button>` puts an inline-sized box between the
   * container and the thing it was laying out, and the row collapses. Passing
   * the class *onto* the trigger keeps the element count the same as before
   * the conversion, which is what makes this a reachability change rather than
   * a visual one. */
  className?: string
}) => {
  const [open, setOpen] = useState(false)

  return (
    <TooltipPrimitive.Provider>
      <TooltipPrimitive.Root open={open} onOpenChange={setOpen}>
        <TooltipPrimitive.Trigger
          asChild={asChild}
          // `cursor-help` on the wrapper only. Over `asChild` the child is a
          // link or a button and already says what it does with its own
          // cursor; overriding that would be this component lying about what
          // pressing does.
          //
          // The four reset utilities are not decoration. `theme.css`
          // deliberately does not import Tailwind's preflight, so a bare
          // `<button>` keeps the user agent's border, grey background and
          // padding — which is what the first three tooltips in `Artifacts`
          // shipped: a chip inside a visible button box. The wrapper exists to
          // put the trigger in the tab order and must otherwise not be seen.
          // `text-left` because a button's UA `text-align: center` would
          // re-centre whatever it wraps.
          className={
            asChild
              ? undefined
              : clsx('p-0 cursor-help border-0 bg-transparent text-left', className)
          }
        >
          {children}
        </TooltipPrimitive.Trigger>
        {/* Mounted only while open, because `useLayer` inside it is what makes
            "registered" and "open" the same fact. Radix's own `Presence` would
            keep the subtree mounted through an exit animation and therefore
            keep the layer registered after the tooltip had gone — a layer
            holding Escape for something invisible. There is no exit animation
            here, so this costs nothing today and forecloses that. */}
        {open ? <TooltipLayer onDismiss={() => setOpen(false)}>{explanation}</TooltipLayer> : null}
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  )
}

/** The floating half, and the only place the two stacks meet.
 *
 * Separate from `Tooltip` because `useLayer` must run exactly while the
 * tooltip is open, and a hook cannot be conditional. Mounting the component
 * conditionally is the same thing said in a way React allows.
 */
const TooltipLayer = ({ onDismiss, children }: { onDismiss: () => void; children: ReactNode }) => {
  // `returnFocus` is `undefined` on purpose rather than by omission: a tooltip
  // never took focus away from anything — the trigger still has it, which is
  // why the tooltip is open — so there is nothing owed back, and the host
  // ignores it for a non-modal layer regardless.
  //
  // `onDismiss` closes the tooltip and nothing else. It is routed through the
  // host rather than left to Radix so that the *host* decides whether this
  // tooltip is the top layer; Radix would decide against its own stack, in
  // which a `Drawer` does not appear at all.
  //
  // `blocked` is the host's answer to "is a modal in front of me", argued once
  // beside it in `useLayer`. **This is the layer it was missing from**, and the
  // reason it was missing is worth keeping: a tooltip takes no focus and has
  // nothing to click, so leaving it live under a drawer looked harmless. It is
  // not quite: the explanation stays in the accessibility tree beneath an
  // `aria-modal` dialog, so a screen-reader user inside the drawer can still
  // reach a sentence about a control they cannot. Harmless-today is also how
  // the `Popover` hole got there, which is the stronger reason.
  const { container, blocked } = useLayer({ modal: false, onDismiss, returnFocus: undefined })

  // No host, no content — see the trade-off argued above `Tooltip`.
  if (!container) return null

  return (
    <TooltipPrimitive.Portal container={container}>
      <TooltipPrimitive.Content
        inert={blocked}
        aria-hidden={blocked ? true : undefined}
        // Radix's documented seam for declining a dismissal. Not
        // `stopPropagation`: the event must still reach the host's `window`
        // listener, which is the thing that decides who owns this keypress.
        onEscapeKeyDown={(event) => event.preventDefault()}
        sideOffset={6}
        // `pointer-events-auto` because `.lay-overlay-host` is `inset: 0` with
        // `pointer-events: none` and each layer turns them back on for itself
        // — the same thing `.lay-layer` does for an `Overlay`, said as a
        // utility here because this content is Radix's element and not ours.
        // Without it Radix's hoverable-content grace area never sees the
        // pointer and the tooltip closes while you are reading it.
        // `border-solid` is spelled out because `theme.css` deliberately does
        // not import Tailwind's preflight, and preflight is what would
        // otherwise supply the default border style — `border` alone sets a
        // width against `border-style: none` and draws nothing. `max-w-[32ch]`
        // is an arbitrary value rather than a token because the measure of a
        // line of prose is not in the palette and should not be: it is stated
        // in characters, which is what it actually is.
        className="pointer-events-auto max-w-[32ch] rounded-md border border-solid border-line-strong bg-bg-raise px-3 py-2 text-sm text-fg shadow-1"
      >
        {children}
        <TooltipPrimitive.Arrow className="fill-bg-raise" />
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Portal>
  )
}
