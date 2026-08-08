/** How an entity type becomes a colour.
 *
 * Its own module, deliberately, rather than living beside the canvas that
 * paints with it: `GraphCanvas` is loaded with `React.lazy` so the ~60 kB
 * force-graph bundle is fetched only when somebody opens the graph pane, and
 * the legend needs these two values. A legend that imported them from
 * `GraphCanvas.tsx` would pull that whole chunk into the main bundle and quietly
 * undo the split. Nothing in here imports anything.
 */

/** The kind palette from `tokens.css`, in the order entity types are assigned
 *  to it.
 *
 * Read off the document rather than written as hexes here, because the tokens
 * file is the one place this console is allowed to name a colour -- a literal
 * in this module would be a second palette that only diverges once somebody
 * edits the first. The list is the same set the event log already uses for
 * its own kinds, so a reader who has learnt those colours is not learning a
 * second scheme for the graph.
 */
export const KIND_TOKENS = [
  '--k-session',
  '--k-message',
  '--k-file',
  '--k-tool',
  '--k-compaction',
  '--k-turn',
] as const

/** A stable colour per entity type.
 *
 * Hashed rather than kept in a lookup table: entity types come from whatever
 * the extraction produced -- `concept`, `fact`, `hypothesis`, `study`, and
 * anything else a future prompt yields -- so a table would need editing every
 * time the corpus grew a new one, and would fall back to grey for exactly the
 * types nobody had thought of yet. Hashing means the same type is always the
 * same colour within and across sessions, which is the property that actually
 * matters when a reader is scanning a drawing.
 */
export const colorForType = (entityType: string, palette: readonly string[]): string => {
  let hash = 0
  for (let index = 0; index < entityType.length; index += 1) {
    hash = (hash * 31 + entityType.charCodeAt(index)) | 0
  }
  // The index is always in range; the fallback is what satisfies the checked
  // indexed access rather than a case that can happen.
  return palette[Math.abs(hash) % palette.length] ?? palette[0] ?? '#6ba7f5'
}
