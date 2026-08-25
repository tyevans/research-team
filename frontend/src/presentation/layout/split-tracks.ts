import { RAIL_TRACK } from './layout-tokens.ts'

/** One column of a `Split`, declared as data rather than as a stylesheet rule.
 *
 * The reason this is data: `panes.css:73` and `use-panes.ts:67-74` describe the
 * same three columns and disagree. The stylesheet says
 * `minmax(300px, 1.05fr) minmax(320px, 1.5fr) minmax(300px, 1.15fr)`; the hook
 * emits `280/1.05`, `320/1.5`, `280/1.05`. Above 1181px the inline style wins
 * and below it the stylesheet does, so crossing the breakpoint silently
 * changes two minima by 20px and the third weight from 1.15 to 1.05, on top of
 * the reflow the breakpoint exists for. Neither file is wrong; they were never
 * read side by side. One declaration cannot disagree with itself. */
export type Track = {
  /** Matches the `id` of the `Pane` that occupies it. Not an index: a column
   *  identified by position is one that silently means something else the day
   *  a pane is inserted. */
  readonly id: string
  /** The floor, in pixels, below which the column stops being usable. */
  readonly min: number
} & (
  | {
      /** Share of the leftover space. */
      readonly weight: number
      readonly max?: never
    }
  | {
      /** A ceiling written in the grid's own units — `25%`, `20rem` — instead
       *  of a share.
       *
       * A union arm rather than an optional field beside `weight`, because a
       * track sized both ways has no meaning and a shape that permits it
       * invites a reader to wonder which wins. `never` is what makes the
       * compiler say so at the declaration rather than here.
       *
       * The distinction is not decoration: a weight is a share of what the
       * *floors* left over, so the same `1fr` is a different fraction of the
       * window at every width, and a sidebar asked to be a quarter of the page
       * cannot be spelled with one. This says the fraction directly. `min`
       * still applies underneath, so a percentage that falls below the floor
       * loses to it rather than crushing the column. */
      readonly max: string
      readonly weight?: never
    }
)

/** The `grid-template-columns` a split should use, or `undefined` when it must
 *  not set one at all.
 *
 * `undefined` is the load-bearing return and the reason this is a function
 * rather than a template string at the call site. Below the widest breakpoint
 * the stylesheet reflows the panes -- two columns, then a single stack -- and
 * an inline `grid-template-columns` outranks a media query, so a `Split` that
 * always emitted a template would silently defeat every responsive rule below
 * it. The session report calls this handoff "genuinely subtle and worth
 * preserving"; here it is one branch with a name.
 *
 * Pure, and exported separately from the component, because this is the part
 * of the layout system a test can actually hold. jsdom lays nothing out, so a
 * test can assert the string and never that the grid it describes is right.
 */
export const splitTemplate = ({
  tracks,
  collapsed,
  wide,
}: {
  tracks: readonly Track[]
  collapsed: ReadonlySet<string>
  /** Whether the viewport is at or above the split's widest breakpoint. */
  wide: boolean
}): string | undefined => {
  if (!wide) return undefined
  return tracks
    .map((track) =>
      collapsed.has(track.id)
        ? RAIL_TRACK
        : `minmax(${String(track.min)}px, ${track.max ?? `${String(track.weight)}fr`})`,
    )
    .join(' ')
}

/** The result of asking to collapse or expand a pane.
 *
 * `refused` rather than throwing or silently returning the input: the caller
 * has to be able to tell "nothing changed because you asked for something
 * impossible" from "nothing changed", because the first one owes the user a
 * sentence and the second does not. */
export interface ToggleResult {
  readonly collapsed: ReadonlySet<string>
  readonly refused: boolean
}

/** Collapse or expand one pane, refusing to hide the last open one.
 *
 * The refusal is not configurable, and that is a decision rather than an
 * oversight. The session panes refuse (S-F17); the research rail does not, and
 * the research report records what that costs -- a folded seeding pane, with
 * fold state persisted across reloads, leaves a reader looking at "nothing has
 * been seeded" with no seeding control anywhere on screen. There is no case
 * for the permissive arm, so there is no flag for it. A layout with nothing in
 * it has no way back except a toggle you can no longer see.
 *
 * **A pane the layout no longer has is dropped rather than counted, and this
 * used to be the opposite.** The stored set is written by whatever shape the
 * view had when a reader last folded something, and views lose panes: the
 * project page had `queue`/`holder`/`material` and now has two tracks, under
 * the same preference group. Anyone who had folded `holder` before that slice
 * carried a set of size 1 into a two-track layout, so folding the sidebar
 * reached size 2 and was refused -- reported as "I can never collapse the
 * queue", with a toast about a rule the layout was not actually up against.
 *
 * The old code counted the stale entry deliberately, on the reasoning that an
 * equality check "would let the last real pane close on the strength of a
 * stale entry". That is the right worry and it was defended on the wrong side:
 * a stale id can no more close a pane than keep one open once it is not in the
 * count at all. Filtering to the ids `tracks` actually declares answers both,
 * and the pruned set is what is returned, so the dead entry is written out of
 * storage the first time a reader touches the layout rather than sitting there
 * until they clear the browser.
 */
export const toggleCollapsed = ({
  tracks,
  collapsed,
  id,
}: {
  tracks: readonly Track[]
  collapsed: ReadonlySet<string>
  id: string
}): ToggleResult => {
  // Only ids this layout declares. Anything else is a fold remembered from a
  // shape the view no longer has, and it is neither open nor closed here.
  const declared = new Set(tracks.map((track) => track.id))
  const next = new Set([...collapsed].filter((folded) => declared.has(folded)))
  if (next.has(id)) {
    next.delete(id)
    return { collapsed: next, refused: false }
  }
  next.add(id)
  // `>=` rather than `===` still, though the filter above means the two now
  // agree on every input: an id not in `tracks` cannot inflate the count, and
  // `id` itself is the only way `next` can exceed it. Kept because the cost of
  // the loose comparison is nothing and the cost of being wrong is a layout
  // with no pane open and no control to reopen one.
  if (next.size >= declared.size) return { collapsed, refused: true }
  return { collapsed: next, refused: false }
}
