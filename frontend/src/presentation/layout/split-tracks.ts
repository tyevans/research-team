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
export interface Track {
  /** Matches the `id` of the `Pane` that occupies it. Not an index: a column
   *  identified by position is one that silently means something else the day
   *  a pane is inserted. */
  readonly id: string
  /** The floor, in pixels, below which the column stops being usable. */
  readonly min: number
  /** Share of the leftover space. */
  readonly weight: number
}

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
        : `minmax(${String(track.min)}px, ${String(track.weight)}fr)`,
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
  const next = new Set(collapsed)
  if (next.has(id)) {
    next.delete(id)
    return { collapsed: next, refused: false }
  }
  next.add(id)
  // `>=` rather than `===`: a caller can hand in a collapsed set naming a pane
  // that no longer exists, and an equality check would let the last real pane
  // close on the strength of a stale entry.
  if (next.size >= tracks.length) return { collapsed, refused: true }
  return { collapsed: next, refused: false }
}
