import * as TabsPrimitive from '@radix-ui/react-tabs'
import clsx from 'clsx'
import type { ReactNode } from 'react'

/** A set of panels, one shown at a time, and the tabs that choose between them.
 *
 * **Tabs are a claim about panels, and that is the whole reason this is a
 * separate primitive from `Choices`.** `role="tab"` carries an `aria-controls`
 * pointing at a `role="tabpanel"`; a tab list with no panels beneath it is a
 * dangling reference, which is a worse answer for a screen reader than the
 * semantics-free buttons it replaced. So the rule for choosing between the two
 * is decidable rather than a matter of taste: if picking swaps *what is
 * rendered below*, it is `Tabs`; if it changes how one panel draws itself, it
 * is `Choices`. `FileView` holds one of each and they looked identical before
 * this — three `.tabs` rows in one header, one of which switched a panel and
 * two of which configured it.
 *
 * **What Radix supplies.** The roving tabindex (one tab stop for the whole
 * list, arrows within it, Home/End), the `aria-controls`/`aria-labelledby`
 * pair in both directions, and unmounting the panel that is not shown. Nothing
 * floats, so unlike `Tooltip`, `Popover` and `Menu` there is no `OverlayHost`
 * bridge here and no second dismissal stack to reconcile: `Tabs` works in a
 * bare render, and its tests need no host.
 *
 * **Activation is manual, against the APG's usual advice.** With automatic
 * activation an arrow key both moves focus and opens the panel, which is the
 * recommendation *when the panels are cheap*. Here `history` mounts
 * `FileHistory`, which fetches; arrowing across a two-tab list would fire a
 * request for a panel the reader never asked to see. React Query would cache
 * it, so the cost is one wasted round trip rather than a bug -- stated plainly
 * because it is the reason this deviates, and the deviation costs a keystroke:
 * arrow, then Enter or Space.
 */
export const Tabs = ({
  value,
  onValueChange,
  children,
  className,
}: {
  /** The open tab's id. Controlled only — every caller here already holds this
   *  state for its own reasons (`FileView` stamps it with the file it belongs
   *  to, so a new file opens on its contents), and an uncontrolled mode would
   *  be a second copy of it to disagree with. */
  value: string
  onValueChange: (value: string) => void
  /** The `TabList` and the `TabPanel`s, in whatever layout the view needs.
   *
   *  `children` rather than a `tabs`/`panels` pair of props because the list
   *  does not always sit directly above the panels: in `FileView` it is the
   *  last item of a header row that also holds the path and two `Choices`.
   *  Passing the layout in would mean this primitive owning that header. */
  children: ReactNode
  className?: string
}) => (
  <TabsPrimitive.Root
    value={value}
    onValueChange={onValueChange}
    activationMode="manual"
    className={className}
  >
    {children}
  </TabsPrimitive.Root>
)

/** The row of tabs. Must be inside a `Tabs`, and Radix throws if it is not. */
export const TabList = ({
  label,
  options,
  className,
}: {
  /** Names the group for a screen reader — "File view", not "tabs". A tab list
   *  is announced by its label and this is the only place to put one; there is
   *  no visible heading beside it to point at. */
  label: string
  options: readonly { id: string; label: string }[]
  className?: string
}) => (
  <TabsPrimitive.List className={clsx('tabs', className)} aria-label={label}>
    {options.map((option) => (
      // No `if (id !== active)` guard on the change, which the hand-rolled
      // version this replaces carried: Radix does not call `onValueChange` for
      // the tab that is already open, so the guard now lives in the library
      // rather than in every call site. `FileView.test.tsx` documents that the
      // old guard had no test and was defence in depth; this is the same
      // defence, held in one place.
      <TabsPrimitive.Trigger key={option.id} value={option.id} className="tab">
        {option.label}
      </TabsPrimitive.Trigger>
    ))}
  </TabsPrimitive.List>
)

/** One panel. Rendered only while its tab is open — Radix unmounts the others,
 *  which is what the ternary it replaces did, so a panel that fetches does not
 *  fetch until it is looked at. */
export const TabPanel = ({
  value,
  children,
  className,
}: {
  value: string
  children: ReactNode
  className?: string
}) => (
  // Radix gives the panel `tabIndex={0}`, and it is kept rather than overridden
  // even though it adds a tab stop that was not there before. The panel this
  // console shows most often is a `CodeBlock` — a scroll region with no
  // focusable content in it at all — and a scroll region nobody can focus
  // cannot be scrolled from the keyboard. Overriding it to -1 would tidy away
  // one keypress and take that with it.
  <TabsPrimitive.Content value={value} className={className}>
    {children}
  </TabsPrimitive.Content>
)
