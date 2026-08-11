import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react'
import { createPortal } from 'react-dom'

/** What a layer tells the host, and can change its mind about.
 *
 * Behind a ref rather than stored in the registry, and this is load-bearing.
 * Every caller writes `onDismiss={() => setOpen(false)}`, so the function has a
 * new identity on every render; putting it in the registry made it a
 * dependency of registration, which meant **every layer unregistered and
 * re-registered on every render of its parent**.
 *
 * That was quietly wrong before it was loudly wrong. Re-registering appends,
 * so a layer that re-rendered jumped to the top of the stack -- the ordering
 * the whole host is built on, silently reshuffled by an unrelated state
 * change. It became visible when the host started paying focus debts on
 * unregister: a re-render looked exactly like a close, and focus was handed
 * back to the page while the dialog was still open.
 *
 * So registration keys on identity and on `modal` alone -- the two things that
 * are genuinely stable for a mounted layer -- and everything mutable is read
 * through here at the moment it is needed. */
interface LayerHandlers {
  readonly onDismiss: (() => void) | undefined
  /** Where focus goes when this layer closes, for a modal that took it.
   *
   * A ref rather than an element, because the layer captures it at the moment
   * it opens -- before it moves focus into itself -- and the host only reads it
   * much later, when the layer is being removed. */
  readonly returnFocus: RefObject<Element | null> | undefined
}

/** One registered layer. `modal` is the only thing the host needs to know
 *  about a layer's content, because it is the only thing that changes what the
 *  layers underneath are allowed to do. */
interface Layer {
  readonly key: number
  readonly modal: boolean
  readonly handlers: RefObject<LayerHandlers>
}

interface HostState {
  readonly container: HTMLElement | null
  readonly register: (layer: Layer) => () => void
  readonly layers: readonly Layer[]
}

const HostContext = createContext<HostState | null>(null)

/** The single place every dismissable layer renders.
 *
 * **What this replaces**, measured in the running console rather than read out
 * of the source: eight `z-index` declarations across five values, of which two
 * arrangements are wrong and one is undecided.
 *
 * - `.agents-panel` at 40 against `.drawer-backdrop` at 20. The dock's popover
 *   is `position: fixed`, the drawer backdrop is `position: fixed; inset: 0`
 *   with `aria-modal="true"` and a focus trap, and no stacking context
 *   intervenes. So **the popover paints on top of the modal backdrop, is not
 *   covered by it, is not `inert`, and has switched off its own Escape and
 *   outside-pointerdown handling because its comment asserts the drawer is in
 *   front.** Two files: one describing an order, the other producing its
 *   opposite.
 * - `.menu > .disc-body` also at 20, *tying* with the modal backdrop. A row
 *   menu against an open dialog is resolved by DOM order today with nothing
 *   anywhere stating which should win. It is benign only because one is fixed
 *   and one is absolute inside a row, which is a property nobody wrote down
 *   and nothing enforces.
 * - `.toasts` at 50, above everything. That one is probably right and is
 *   currently right by accident; `tokens.css` promotes it to a stated role.
 *
 * **Why one host fixes it structurally rather than by re-tuning.** Every layer
 * here shares one `z-index` (`--z-overlay`), so paint order is DOM order and
 * DOM order is the order layers mounted. A drawer opened *from* the dock
 * mounts after the dock's popover and is therefore above it -- which is what
 * the dock's comment already claims and the stylesheet already denies. There
 * is no number to get wrong because there is no number.
 *
 * The three things that follow, each of which is a defect today:
 *
 * - **A modal makes everything beneath it inert.** Not a convention: the host
 *   sets the `inert` attribute on every layer below the topmost modal, so the
 *   popover is unclickable and unfocusable while a drawer is open, instead of
 *   being live and painted on top of the thing that claims to be modal.
 * - **Escape belongs to the topmost layer.** The host owns the key listener
 *   and calls exactly one `onDismiss`. The dock's guard -- "with a feed open
 *   the drawer is in front and owns Escape" -- is a rule a component should
 *   never have had to reason about, and under this host it is deleted rather
 *   than restated.
 * - **Stacking is not a parameter.** A per-view stacking order is how a
 *   codebase gets four z-index values and a comment describing the wrong one.
 *
 * Toasts stay **outside** this host, at `--z-toast`, above every layer in it.
 * That is deliberate and is argued where the token is declared: a toast is not
 * a dismissable layer -- the reader did not open it, it takes no focus, and it
 * has to stay readable over whatever is open, because something failing while
 * a dialog is up is exactly when the reader needs to hear about it.
 *
 * **Where this stands now.** Among layers that use this host the bad
 * arrangement cannot be expressed: there is no per-layer number to set, so a
 * popover cannot outrank a modal, and a layer beneath a modal is `inert`
 * rather than merely painted-under.
 *
 * The phase that introduced this host said plainly that the guarantee
 * "protects nothing that exists" until two further things landed: the existing
 * overlays moved onto it, and a rule forbidding a literal `z-index` so a ninth
 * could not appear. **Both have now landed.** `Drawer` (and therefore
 * `Confirm`, `WorkerDrawer` and the document reader) and the agent dock's
 * popover are layers; `.drawer-backdrop` at 20 and `.agents-panel` at 40 are
 * deleted rather than retuned, and `scripts/check-deleted.mjs` fails if either
 * comes back. `scripts/stacking.test.ts` fails the build on any `z-index` that
 * is not a `var(--z-*)` declared in `tokens.css`, and on a fourth role being
 * added to that scale -- which is the loophole a rule about literals alone
 * would leave wide open.
 *
 * So the claim is now the strong one: a new overlay cannot give itself a
 * stacking order. It can only name one of three declared roles, and the only
 * role that paints over the page is this host.
 *
 * Two things stayed off the host **on purpose**, because moving them would
 * have been worse:
 *
 * - **Toasts**, argued below and where `--z-toast` is declared: a toast is not
 *   a dismissable layer.
 * - **The row menu** in `ProjectList`. It is a `Disclosure` anchored to its
 *   own row by ordinary absolute positioning. The host is one fixed box over
 *   the viewport and deliberately offers no anchoring, so portalling a
 *   row-anchored menu would mean measuring the row and tracking it on scroll
 *   -- inventing a positioning engine to solve a stacking problem the menu no
 *   longer has. Its tie with the modal backdrop was the whole complaint, and
 *   the tie is gone because the backdrop is gone: the menu sits at
 *   `--z-sticky` (10), a modal is at `--z-overlay` (100), and while a modal is
 *   open the menu is inside `.lay-app-root` and therefore `inert`. If a menu
 *   ever does need to escape its pane, the answer is anchoring on this host,
 *   not a number on the menu.
 */
export const OverlayHost = ({ children }: { children?: ReactNode }) => {
  const [container, setContainer] = useState<HTMLElement | null>(null)
  const [layers, setLayers] = useState<readonly Layer[]>([])

  /** Where focus owes to go once the page stops being inert.
   *
   * **Why the host does this and not the layer that wants it.** A closing
   * modal gives focus back to the row that opened it, and focusing into an
   * inert subtree does nothing at all -- so the restore has to land *after*
   * this component re-renders without `inert`. Nothing inside the closing
   * layer can arrange that. Measured in Chromium by logging the attribute from
   * a layer's own unmount cleanup while closing a drawer: still inert
   * synchronously, still inert at the microtask checkpoint, still inert inside
   * `requestAnimationFrame`, clear only by `setTimeout(0)`. `useLayoutEffect`
   * on the registration does not fix it either -- React defers the resulting
   * render past the closing layer's passive cleanup.
   *
   * So `Drawer` did the obvious correct-looking thing, focus was silently
   * refused, and the reader was dropped on `<body>` -- back at the top of the
   * document, which is the exact outcome focus restoration exists to prevent.
   * The effect below runs after *this* component's own re-render, which is the
   * render that removes the attribute, so by then the page is live and a plain
   * `focus()` works. That is an ordering guarantee rather than a delay tuned to
   * beat a scheduler.
   *
   * **jsdom cannot see any of this.** It implements `inert`'s presence and none
   * of its behaviour, so every arrangement above passes every test in this
   * repository. Found by tabbing in a browser; `FocusReturnsToTheRow` is the
   * story that shows it. */
  const owedFocus = useRef<Element | null>(null)

  const register = useCallback((layer: Layer) => {
    setLayers((current) => [...current, layer])
    return () => {
      // Read at removal rather than at registration: the layer captured it
      // before moving focus into itself, and reading it here is what makes
      // "the element that opened this" survive everything in between.
      const owed = layer.handlers.current.returnFocus?.current
      if (layer.modal && owed) owedFocus.current = owed
      setLayers((current) => current.filter((each) => each.key !== layer.key))
    }
  }, [])

  useEffect(() => {
    if (layers.length === 0) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      // Exactly one layer is dismissed, and it is the last one that asked to
      // be. Without a single owner, two overlays both listening on `window`
      // both close on one keypress -- which is why the session view's timeline
      // calls `stopPropagation` so "one Escape does not fold twice".
      const top = layers[layers.length - 1]
      const dismiss = top?.handlers.current.onDismiss
      if (!dismiss) return
      event.preventDefault()
      dismiss()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [layers])

  const state = useMemo<HostState>(
    () => ({ container, register, layers }),
    [container, register, layers],
  )

  const modalOpen = layers.some((layer) => layer.modal)

  // The restore itself. Keyed on `layers` rather than on "is anything still
  // modal", because a stack has to unwind one step at a time: closing a
  // confirm that was opened from a drawer owes focus to the control *inside
  // the drawer* that opened it, and that control is live even though the page
  // behind is not. Waiting for the last modal to leave would skip that step
  // and strand the reader. Each layer names its own target, so each close
  // returns focus exactly one level out.
  //
  // This runs after the host has re-rendered, which is the render that updates
  // `inert`, so the target is reachable by the time it is focused -- the whole
  // reason the restore lives here instead of in the layer.
  //
  // DOM membership is re-checked: the row may have been removed while the
  // layer was open -- a list refetched underneath it -- and focusing a detached
  // node throws in some environments and silently no-ops in others, neither of
  // which puts focus anywhere useful.
  useEffect(() => {
    const owed = owedFocus.current
    if (!owed) return
    owedFocus.current = null
    if (owed instanceof HTMLElement && document.contains(owed)) owed.focus()
  }, [layers])

  return (
    <HostContext.Provider value={state}>
      {/* The page, and the thing a modal has to take away.

          This wrapper exists only to have something to mark. Before it,
          `children` was rendered as a bare fragment, so a modal made every
          *other layer* inert and left the whole shell reachable: pointer
          events were blocked by the backdrop, and Tab was not. A keyboard user
          tabbed out of an `aria-modal` dialog straight into page chrome, and a
          screen-reader user was never confined. That is the primitive's
          central promise and it was the one thing nothing asserted -- the
          jsdom test checked `inert` on the sibling layer, which was true, and
          said nothing about everything else. Found in a browser, which is
          where it had to be found.

          **Why the host owns this rather than `Shell` subscribing to modal
          state.** Both work and the trade is which way the coupling points.
          `Shell` reading the host would make "a modal disables the page" a
          property of one component, so it would hold for a `Shell` and not for
          any other tree an `OverlayHost` wraps -- including every story here
          that mounts overlays without one, and any future host mounted around
          something that is not the shell. Putting it here makes the guarantee
          a property of *being inside a host*, which is the same scope as the
          rest of the contract, and costs `Shell` no knowledge of overlays at
          all. The price is this extra element in everyone's DOM.

          `display: contents`, so the box does not exist for layout and the
          tree lays out exactly as it did when this was a fragment --
          `.lay-shell`'s `height: 100%` still resolves against the same
          ancestor it did before.

          **The one assumption in this fix that cannot be checked from here.**
          Inertness is specified over the node tree rather than the box tree,
          so an element generating no box should still make its descendants
          inert. That is what the standard says and what every implementation
          I know of does, and jsdom cannot confirm it because jsdom implements
          the attribute's presence and none of its behaviour -- the tests
          beside this file model reachability by walking for the attribute,
          which would pass whether or not a browser honours it here. So this
          is the line to check first if the fix appears not to work: if
          `display: contents` turns out to defeat `inert`, the answer is to
          give this element a real box that fills its parent rather than to
          reach for `aria-hidden` alone. */}
      <div className="lay-app-root" inert={modalOpen} aria-hidden={modalOpen ? true : undefined}>
        {children}
      </div>
      {/* `inset: 0` with `pointer-events: none`, so the host covers the page
          for painting purposes and intercepts nothing. Each layer turns
          pointer events back on for itself; a layer that wants to swallow
          clicks renders its own backdrop, which is a decision belonging to
          the layer rather than to the host.

          A sibling of the wrapper above rather than inside it, which is what
          keeps the layers reachable while the page is not. */}
      <div className="lay-overlay-host" ref={setContainer} />
    </HostContext.Provider>
  )
}

/** A place in the layer stack, without any opinion about rendering.
 *
 * Extracted from `Overlay` so that something which is *not* an overlay can
 * still take its turn at Escape. `GraphDetail` is the case: it is a panel laid
 * out beside the canvas rather than floating over it, so it must not be
 * portalled, must not be `inert`-ed and must not trap focus -- and yet it
 * closes on Escape, which means it is competing for the same key as every
 * drawer and popover in the console. Listening on `window` itself, which is
 * what it did, is exactly the arrangement the host exists to remove: one
 * keypress closed the panel *and* whatever was in front of it.
 */
const useLayer = ({
  modal,
  onDismiss,
  returnFocus,
}: {
  modal: boolean
  onDismiss: (() => void) | undefined
  returnFocus: RefObject<Element | null> | undefined
}) => {
  const host = useContext(HostContext)
  // A stable identity per mount. `useState` with a lazy initialiser rather
  // than `useRef(nextKey()).current`: the ref version reads `.current` during
  // render, which `react-hooks` rejects and is right to -- a value read during
  // render is one React may not have the version of it thinks it has. `useId`
  // would also be stable, but the host compares keys to remove layers and a
  // monotonic number makes "later means on top" literally true rather than
  // incidentally so.
  const [key] = useState(nextKey)

  // Everything the host may want to call, kept current without making any of
  // it a registration dependency -- see `LayerHandlers` for what went wrong
  // when `onDismiss` was one.
  //
  // Updated in a layout effect rather than during render, because writing a
  // ref during render is a real hazard and `react-hooks/refs` rejects it: a
  // render React discards would leave the ref holding callbacks from a tree
  // that never committed. A layout effect runs synchronously after the commit
  // and before the browser can deliver any event, so nothing can read a stale
  // callback in between -- which is the property the render-time write was
  // reaching for, obtained safely.
  const handlers = useRef<LayerHandlers>({ onDismiss, returnFocus })
  useLayoutEffect(() => {
    handlers.current = { onDismiss, returnFocus }
  })

  const { register, layers, container } = host ?? {}

  // **`useLayoutEffect`, not `useEffect`, and the difference is observable.**
  //
  // Registration drives `inert` on `.lay-app-root`, so unregistering is what
  // *lifts* it. Under `useEffect` that lift is a passive-effect state update,
  // which React flushes on a later macrotask -- measured in Chromium by
  // logging the attribute at four points while closing a drawer: still inert
  // synchronously, still inert at the microtask checkpoint, still inert inside
  // `requestAnimationFrame`, clear only by `setTimeout(0)`.
  //
  // That is not an abstract concern. A closing dialog gives focus back to the
  // row that opened it, and focusing into an inert subtree does nothing at
  // all, so with a passive registration the reader was dropped on `<body>` --
  // the exact outcome focus restoration exists to prevent. A layout effect's
  // state update is flushed before the browser paints and before passive
  // cleanups run, so by the time `Drawer` restores focus the page is live
  // again and a plain synchronous `focus()` works.
  //
  // The cost is that registration now runs on the layout path, which is
  // synchronous and blocks paint. It is two `setState` calls on an array of at
  // most a handful of layers, so the cost is real but tiny -- and the
  // alternative was every consumer deferring its own focus call by a timer
  // chosen to beat React's scheduler, which is a race dressed up as a fix.
  //
  // jsdom cannot see any of this: it implements `inert`'s presence and none of
  // its behaviour, so both versions pass every test in this repository. Found
  // in a browser, which is the only place it was ever visible.
  useLayoutEffect(() => {
    if (!register) return
    return register({ key, modal, handlers })
  }, [register, key, modal, handlers])

  return {
    host,
    container,
    layers,
    /** This layer's position in the stack, or -1 before it has registered. */
    mine: layers?.findIndex((layer) => layer.key === key) ?? -1,
  }
}

/** Take a turn at Escape without rendering an overlay.
 *
 * For something that closes on Escape but is laid out in the page rather than
 * floating over it. The host gives Escape to the topmost registered layer and
 * to nothing else, so a panel that registers here stops closing at the same
 * time as the drawer in front of it -- which is what a `window` listener does,
 * because `inert` blocks focus and pointers and has no opinion at all about
 * keydown listeners bound to `window`.
 *
 * Non-modal by construction. A thing that wanted to be modal would want a
 * backdrop and confinement too, and that is `Overlay`.
 */
export const useEscape = (onDismiss: () => void): void => {
  useLayer({ modal: false, onDismiss, returnFocus: undefined })
}

/** One dismissable layer, rendered into the host through a portal.
 *
 * Nothing in this codebase calls `createPortal` today — every overlay renders
 * inline in the React tree and escapes only through `position: fixed`. That is
 * why this is new capability rather than a refactor, and it is the reason the
 * ordering above is achievable at all: layers cannot be ordered by DOM
 * position while they are scattered across the tree at the mercy of whichever
 * ancestor happens to create a stacking context.
 */
export const Overlay = ({
  label,
  modal = false,
  onDismiss,
  anchor,
  returnFocus,
  children,
}: {
  /** The accessible name. Required rather than optional: an unnamed dialog is
   *  announced as "dialog" and nothing else, which is the state
   *  `Drawer`'s `label` prop exists to prevent. */
  label: string
  /** Whether this layer takes the page. A modal renders a backdrop, and every
   *  layer beneath it in the host becomes inert. */
  modal?: boolean
  /** Escape, and a click on the backdrop of a modal. Omit for a layer that
   *  must not be dismissable, and understand that it then blocks Escape for
   *  everything beneath it. */
  onDismiss?: () => void
  /** The control this layer hangs off, for a **non-modal** layer only.
   *
   * A popover is dismissed by pointing anywhere else, and "anywhere else" has
   * to exclude the toggle that opened it or the press closes the layer and the
   * click that follows immediately reopens it. That is the whole reason this
   * prop exists, and it is the one fact about a popover the host cannot work
   * out for itself: the toggle is in the page, the layer is in the portal, and
   * nothing in the DOM connects them.
   *
   * Omit it and outside-pointer dismissal still runs -- a layer with no anchor
   * simply has nothing to exclude, which is correct for a menu opened from
   * something that is not a persistent toggle. */
  anchor?: RefObject<HTMLElement | null>
  /** Where focus goes when this layer closes, for a **modal** that moved focus
   *  into itself.
   *
   * The layer captures the element as it opens and the host performs the
   * restore, because only the host knows when the page stops being `inert` --
   * argued at length beside `owedFocus`. A ref rather than an element so the
   * caller can fill it in at the right moment rather than at render time.
   *
   * Ignored for a non-modal layer, which never took focus away from anything
   * and has nothing to give back. */
  returnFocus?: RefObject<Element | null>
  children: ReactNode
}) => {
  const { host, container, layers, mine } = useLayer({ modal, onDismiss, returnFocus })
  // Inert if any *later* layer is modal. Later, not "any", because a modal
  // does not make itself inert and does not disable the layers stacked on top
  // of it -- a confirm opened from a drawer has to stay usable.
  const blocked = mine >= 0 && (layers ?? []).some((layer, index) => index > mine && layer.modal)

  const contentRef = useRef<HTMLDivElement>(null)

  // Pointing anywhere else dismisses a non-modal layer.
  //
  // **Why this is the primitive's job and not each popover's.** It was the
  // dock's, in twelve lines that had to know a drawer might be in front (`if
  // (!expanded || watching) return`) -- a popover reasoning about what else
  // was open, which is precisely the coupling this host exists to remove. One
  // implementation here is also one place for the two decisions that are easy
  // to get wrong separately, both inherited verbatim from the dock's version:
  //
  // - `pointerdown`, not `click`, so the layer is gone *before* the press
  //   lands on whatever is underneath and that press still does its job. With
  //   `click` the first press is spent closing the popover.
  // - no focus return, deliberately. The reader is pressing something else and
  //   is about to be somewhere else; yanking focus back to the toggle is right
  //   for Escape and wrong for a pointer. Escape's focus return belongs to the
  //   caller's `onDismiss`, which is where the dock still does it.
  //
  // Modal layers are excluded because a modal's backdrop already covers this
  // and covers it better: a press outside a modal never reaches the page at
  // all, and routing it through here would dismiss on presses the backdrop
  // has already swallowed. `blocked` layers are excluded because a layer under
  // a modal is inert -- it should not be reacting to presses it cannot see.
  const dismissable = !modal && !blocked && onDismiss !== undefined
  useEffect(() => {
    if (!dismissable) return
    const onDown = (event: PointerEvent) => {
      const target = event.target
      if (!(target instanceof Node)) return
      if (contentRef.current?.contains(target)) return
      if (anchor?.current?.contains(target)) return
      onDismiss?.()
    }
    window.addEventListener('pointerdown', onDown)
    return () => window.removeEventListener('pointerdown', onDown)
  }, [dismissable, onDismiss, anchor])

  if (!host || !container) return null

  return createPortal(
    <div
      className="lay-layer"
      data-modal={modal ? '' : undefined}
      // React 19 renders `inert` as a real attribute. jsdom does not implement
      // what it *does*, so the tests here assert the attribute is present and
      // cannot assert that focus is actually blocked; a browser check is the
      // only thing that closes that.
      inert={blocked}
      aria-hidden={blocked ? true : undefined}
    >
      {modal ? (
        <>
          {/* A backdrop is not a control, and the keyboard route the rule is
              asking for exists one level up: the host owns Escape and gives it
              to the topmost layer. Satisfying the rule here would add a second
              route to the same behaviour rather than a first route to a
              missing one. The disable sits on its own line above the element
              because a directive written among the attributes attaches to the
              wrong line and reports as unused. */}
          {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */}
          <div className="lay-layer-backdrop" onClick={onDismiss} />
        </>
      ) : null}
      <div
        className="lay-layer-content"
        ref={contentRef}
        role="dialog"
        aria-modal={modal}
        aria-label={label}
      >
        {children}
      </div>
    </div>,
    container,
  )
}

let counter = 0
const nextKey = () => (counter += 1)
