import { createContext, useContext, useMemo, type ReactNode } from 'react'

import { splitTemplate, toggleCollapsed, type Track } from './split-tracks.ts'
import { useWide } from './use-wide.ts'

interface SplitState {
  readonly collapsed: ReadonlySet<string>
  readonly toggle: (id: string) => void
  /** False below the widest breakpoint, where the stylesheet owns the shape. */
  readonly wide: boolean
  /** True below `narrow`, where the panes stop being columns at all.
   *
   *  Separate from `wide`, and the separation was found by migrating the
   *  session view onto this rather than by reasoning about it. A pane chooses
   *  between a vertical rail and a horizontal strip on *this*, not on `wide`:
   *  between the two breakpoints the session panes are still columns -- two of
   *  them, with the third wrapped to its own row -- and a collapsed one is
   *  still a 34px rail with its title on its side. Switching on `wide` turned
   *  every collapsed pane into a strip at 1000px, where today it is a rail. */
  readonly stacked: boolean
}

/** How a `Pane` learns whether it is collapsed without every view threading it
 *  through by hand.
 *
 *  Context, used the way Radix uses it for compound components — provided by
 *  the parent primitive, consumed by its own children, never reaching outside
 *  the pair. This is not the store access the props-only rule forbids: nothing
 *  here is application state, and `Pane` takes explicit props that win over
 *  the context, so it still renders standalone from props alone and still
 *  earns a story. The alternative, passing `collapsed` and `onToggle` to both
 *  `Split` and every `Pane`, states the same fact three times at every call
 *  site and lets two of them disagree. */
const SplitContext = createContext<SplitState | null>(null)

export const useSplit = () => useContext(SplitContext)

/** A row of resizable regions that owns its own sizing.
 *
 * Everything about how wide a column is lives in `tracks`, once. The two
 * declarations this replaces disagreed with each other (see `split-tracks.ts`).
 *
 * No `axis` prop. The design sketch had one, and there is no second axis in
 * this console: below `--bp-narrow` the panes stack, but that is the
 * responsive mode rather than a different split, and it is owned by the
 * stylesheet. A prop with one legal value is how a primitive becomes a
 * configuration language.
 */
export const Split = ({
  id,
  label,
  tracks,
  collapsed,
  onCollapsedChange,
  onRefuse,
  children,
}: {
  id: string
  /** Names the group for a screen reader. `Split` is a landmark-less
   *  container, so without this a reader meets three unrelated regions. */
  label: string
  tracks: readonly Track[]
  collapsed: ReadonlySet<string>
  onCollapsedChange: (collapsed: ReadonlySet<string>) => void
  /** Called instead of `onCollapsedChange` when the last open pane would have
   *  been hidden. The primitive refuses; saying so is the view's job, because
   *  the view owns the toast and this component must not reach for one. */
  onRefuse?: () => void
  children: ReactNode
}) => {
  const wide = useWide('wide')
  const stacked = !useWide('narrow')

  const state = useMemo<SplitState>(
    () => ({
      collapsed,
      wide,
      stacked,
      toggle: (paneId: string) => {
        const result = toggleCollapsed({ tracks, collapsed, id: paneId })
        if (result.refused) onRefuse?.()
        else onCollapsedChange(result.collapsed)
      },
    }),
    [collapsed, wide, stacked, tracks, onCollapsedChange, onRefuse],
  )

  return (
    <SplitContext.Provider value={state}>
      <div
        className="lay-split"
        data-split={id}
        aria-label={label}
        role="group"
        // `undefined` below the breakpoint, deliberately, so the media queries
        // in the stylesheet keep their say. React omits the property entirely
        // rather than writing an empty one, which is what makes the handoff
        // work at all -- an inline style outranks any media query.
        style={{ gridTemplateColumns: splitTemplate({ tracks, collapsed, wide }) }}
      >
        {children}
      </div>
    </SplitContext.Provider>
  )
}
