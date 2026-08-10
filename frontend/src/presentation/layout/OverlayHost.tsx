import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'

/** One registered layer. `modal` is the only thing the host needs to know
 *  about a layer's content, because it is the only thing that changes what the
 *  layers underneath are allowed to do. */
interface Layer {
  readonly key: number
  readonly modal: boolean
  readonly onDismiss: (() => void) | undefined
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
 * **Where this is honestly not closed, stated plainly.** Among layers that use
 * this host the bad arrangement cannot be expressed: there is no per-layer
 * number to set, so a popover cannot outrank a modal, and a layer beneath a
 * modal is `inert` rather than merely painted-under. That is a real structural
 * guarantee.
 *
 * It is also a smaller guarantee than "fixed", because **nothing forces an
 * overlay to use the host.** A component can still write `position: fixed;
 * z-index: 40` in a stylesheet and reproduce the inversion exactly, and every
 * one of the eight declarations above still does. This phase migrates none of
 * them, so today the guarantee protects nothing that exists -- it is the floor
 * the migration stands on, not the migration. Closing it needs both halves:
 * the existing overlays moved onto this host, and a rule forbidding `z-index`
 * outside `tokens.css` so a ninth cannot appear. Neither is in this phase, and
 * claiming the defect is fixed before both have landed would be false.
 */
export const OverlayHost = ({ children }: { children?: ReactNode }) => {
  const [container, setContainer] = useState<HTMLElement | null>(null)
  const [layers, setLayers] = useState<readonly Layer[]>([])

  const register = useCallback((layer: Layer) => {
    setLayers((current) => [...current, layer])
    return () => setLayers((current) => current.filter((each) => each.key !== layer.key))
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
      if (!top?.onDismiss) return
      event.preventDefault()
      top.onDismiss()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [layers])

  const state = useMemo<HostState>(
    () => ({ container, register, layers }),
    [container, register, layers],
  )

  const modalOpen = layers.some((layer) => layer.modal)

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
  children: ReactNode
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

  const { register, layers, container } = host ?? {}

  useEffect(() => {
    if (!register) return
    return register({ key, modal, onDismiss })
  }, [register, key, modal, onDismiss])

  if (!host || !container) return null

  const mine = layers?.findIndex((layer) => layer.key === key) ?? -1
  // Inert if any *later* layer is modal. Later, not "any", because a modal
  // does not make itself inert and does not disable the layers stacked on top
  // of it -- a confirm opened from a drawer has to stay usable.
  const blocked = mine >= 0 && (layers ?? []).some((layer, index) => index > mine && layer.modal)

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
      <div className="lay-layer-content" role="dialog" aria-modal={modal} aria-label={label}>
        {children}
      </div>
    </div>,
    container,
  )
}

let counter = 0
const nextKey = () => (counter += 1)
