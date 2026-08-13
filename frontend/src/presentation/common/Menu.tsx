import * as MenuPrimitive from '@radix-ui/react-dropdown-menu'
import clsx from 'clsx'
import type { ReactNode } from 'react'

import { useLayer } from '../layout/OverlayHost.tsx'

/** A button that opens a list of verbs.
 *
 * **The same bridge as `Tooltip` and `Popover`, third time unchanged**: portal
 * into the host's container so the content shares `--z-overlay`, `useLayer`
 * while open so the host orders it, and `onEscapeKeyDown` prevented so the
 * keypress reaches the host's listener instead of being answered from Radix's
 * own stack. Three primitives, one seam, no per-component reasoning about what
 * else is open.
 *
 * **What it replaces, and why that was not merely untidy.** The row menu on a
 * project was a `Disclosure` with different chrome -- `tree.css` said so:
 * "A `Disclosure` with different chrome, which is all a menu is here." It is
 * not. A disclosure announces `aria-expanded` over a region it controls; a
 * menu announces `role="menu"` with `role="menuitem"` children, moves between
 * those children with Up and Down rather than Tab, closes on Escape and gives
 * focus back to the button that opened it. The disclosure version had the
 * first of those and none of the rest, so a keyboard reader tabbed *into* the
 * menu, tabbed *through* it into the rest of the row, and had no way back. It
 * also positioned itself with `.menu > .disc-body { position: absolute; right:
 * 0 }`, which cannot leave the row it is anchored in -- `OverlayHost`'s
 * docstring records that as the reason the row menu stayed off the host, and
 * names the fix as "anchoring on this host, not a number on the menu". This is
 * that: Radix brings the anchoring, the host keeps the stacking.
 *
 * **`modal={false}`, and it is the one line here that is easy to get wrong.**
 * Radix's `DropdownMenu` defaults to `modal: true`, which marks everything
 * outside the menu `aria-hidden` and blocks pointer events on it. That is a
 * second implementation of what `OverlayHost` does with `inert`, deciding from
 * a stack that has never heard of a `Drawer` -- the two-authorities problem
 * this bridge exists to remove, arriving switched on by default. A menu is not
 * modal in this console; a thing that takes the page is a `Drawer`.
 *
 * The cost is the one every floating primitive here pays: with no
 * `OverlayHost` in scope the menu opens onto nothing at all.
 */
export const Menu = ({
  open,
  onOpenChange,
  label,
  trigger,
  align = 'end',
  children,
}: {
  open: boolean
  /** Controlled, like `Popover` and for the same reason: the state usually
   *  belongs to the row, which knows when the row went away. */
  onOpenChange: (open: boolean) => void
  /** The accessible name of the list. Radix names the *trigger* from its
   *  content, which is a `⋯` at the one call site here and therefore names
   *  nothing; this is what a screen reader reads when it enters the menu. */
  label: string
  /** The button. Rendered with `asChild`, so it must be a real `<button>` that
   *  forwards a `ref`. Radix supplies `aria-haspopup="menu"`, `aria-expanded`
   *  and `aria-controls`. */
  trigger: ReactNode
  align?: 'start' | 'center' | 'end'
  /** `MenuItem`s. Anything else in here is outside the menu's keyboard
   *  contract -- Radix moves between `role="menuitem"` children and skips
   *  whatever it does not recognise, so a stray `<button>` becomes a control
   *  that arrow keys cannot reach and Tab cannot reach either. */
  children: ReactNode
}) => (
  <MenuPrimitive.Root open={open} onOpenChange={onOpenChange} modal={false}>
    <MenuPrimitive.Trigger asChild>{trigger}</MenuPrimitive.Trigger>
    {/* Mounted only while open, so that "registered with the host" and "open"
        are the same fact -- argued at length in `Tooltip`. */}
    {open ? (
      <MenuLayer label={label} align={align} onDismiss={() => onOpenChange(false)}>
        {children}
      </MenuLayer>
    ) : null}
  </MenuPrimitive.Root>
)

/** The `⋯` button, for the two rows that have one.
 *
 * A component rather than the `.menu-trigger` class it replaces, and the
 * reason is where that class lived: `tree.css`, a *screen* stylesheet, which
 * the topic row is not in and which phase 5 deletes with its screen. The
 * choices were to copy six declarations into `entity.css` or to move them to
 * the primitive that owns the trigger, and a duplicated rule is how two
 * `⋯` buttons come to look different for no reason anybody chose.
 *
 * `aria-label` is required rather than optional, because the label is the
 * whole accessibility of this button: `⋯` names nothing, and a list of rows
 * each offering "More actions" is a screen-reader reading with no way to tell
 * which row it is on. Name it after the row.
 *
 * It takes and spreads `rest` because Radix's `Trigger asChild` clones it with
 * `aria-haspopup`, `aria-expanded`, `aria-controls`, `data-state` and a ref.
 * Dropping them would leave a button that opens a menu and says nothing about
 * it -- which is the failure the `Disclosure` version had, arriving a second
 * way.
 */
export const MenuTrigger = ({
  'aria-label': label,
  ...rest
}: { 'aria-label': string } & React.ComponentPropsWithoutRef<'button'>) => (
  <button
    type="button"
    aria-label={label}
    // `border-solid` spelled out for the reason given on the content below:
    // `theme.css` does not import Tailwind's preflight, so `border` alone sets
    // a width against `border-style: none` and draws nothing. `leading-none`
    // is what keeps this to the row's height -- the glyph's line box is taller
    // than the character, and a trigger a few pixels taller than the buttons
    // beside it grows the row, which is the height contract `TopicRow` is
    // built on.
    className="cursor-pointer rounded-md border border-solid border-line bg-bg-panel-2 px-2 py-1 leading-none text-fg-dim"
    {...rest}
  >
    ⋯
  </button>
)

/** One verb.
 *
 * A thin wrapper rather than a re-export, and the reason is the styling below
 * rather than the handler: `data-[highlighted]` is the only way to draw the
 * arrow-key selection, and a call site left to write that itself would write
 * it differently in each menu.
 *
 * `onSelect` rather than `onClick` because it is the event that means what a
 * menu means -- it fires for Enter, Space and a click alike, before the menu
 * closes, and it can decline the close. **It is not, however, the difference
 * between working and not working with a keyboard**: an `onClick` on a
 * `DropdownMenu.Item` also fires on Enter, because Radix synthesises a click.
 * That was assumed here and written down as fact, and the test meant to hold
 * it -- `runs an item on Enter` -- stayed green with `onSelect` swapped for
 * `onClick`. Recorded rather than quietly corrected, because a wrapper
 * justified by a reason that turns out to be false is a wrapper somebody will
 * delete.
 */
export const MenuItem = ({
  onSelect,
  disabled = false,
  tone,
  children,
}: {
  onSelect: () => void
  disabled?: boolean
  /** `danger` for a verb that destroys something. There is no `primary`: a
   *  menu is where the things that are not the row's obvious action live, so a
   *  highlighted item in one is a button in the wrong place. */
  tone?: 'danger'
  children: ReactNode
}) => (
  <MenuPrimitive.Item
    disabled={disabled}
    onSelect={onSelect}
    // `data-[highlighted]` rather than `:hover`, because a menu item is
    // highlighted by the arrow keys as well as by the pointer and Radix is the
    // only thing that knows which is current. Styling `:hover` alone is how a
    // menu ends up looking, to a keyboard reader, as though nothing is
    // selected. `outline-none` for the same reason -- the highlight *is* the
    // focus indicator here, and a ring on top of it draws two.
    className={clsx(
      'rounded-sm py-1.5 flex w-full cursor-pointer items-center px-3 text-sm outline-none select-none',
      'data-[disabled]:cursor-default data-[disabled]:text-fg-faint data-[highlighted]:bg-bg-hover',
      tone === 'danger' ? 'text-k-failure' : 'text-fg',
    )}
  >
    {children}
  </MenuPrimitive.Item>
)

/** The floating half, and the only place the two dismissal stacks meet. */
const MenuLayer = ({
  label,
  align,
  onDismiss,
  children,
}: {
  label: string
  align: 'start' | 'center' | 'end'
  onDismiss: () => void
  children: ReactNode
}) => {
  // Routed through the host so the *host* decides whether this menu is the top
  // layer. See `Popover` for why closing by prop still returns focus to the
  // trigger: Radix's focus scope restores on unmount whatever caused it, and
  // `closes on Escape and gives focus back to the trigger` is the assertion
  // that fails if that stops being true.
  //
  // `blocked` is the host's answer to "is a modal in front of me" -- applied
  // here because Radix content is portalled in without an `Overlay` around it
  // to carry the attributes. Argued once beside `blocked` in `useLayer`.
  const { container, blocked } = useLayer({ modal: false, onDismiss, returnFocus: undefined })

  if (!container) return null

  return (
    <MenuPrimitive.Portal container={container}>
      <MenuPrimitive.Content
        aria-label={label}
        inert={blocked}
        aria-hidden={blocked ? true : undefined}
        align={align}
        sideOffset={4}
        onEscapeKeyDown={(event) => event.preventDefault()}
        // Declined for the same reason as in `Popover`, and it matters less
        // here: a menu is a short-lived thing and a modal opening over one is
        // rare. It is kept identical anyway, because two floating primitives
        // that dismiss differently under the same event is exactly the kind of
        // difference nobody discovers deliberately.
        onFocusOutside={(event) => event.preventDefault()}
        // `pointer-events-auto` because `.lay-overlay-host` is `inset: 0` with
        // `pointer-events: none`; each layer turns them back on for itself.
        // `border-solid` spelled out because `theme.css` deliberately does not
        // import Tailwind's preflight, so `border` alone sets a width against
        // `border-style: none` and draws nothing. `min-w-[10rem]` so a
        // one-item menu is not narrower than the word in it.
        className="pointer-events-auto min-w-[10rem] rounded-md border border-solid border-line bg-bg-raise p-1 shadow-1"
      >
        {children}
      </MenuPrimitive.Content>
    </MenuPrimitive.Portal>
  )
}
