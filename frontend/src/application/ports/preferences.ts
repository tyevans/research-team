/** Reader preferences that outlive a page load.
 *
 * A port rather than a direct `localStorage` call because storage throws in
 * private mode and in a browser with it disabled, and because the console must
 * survive junk left behind by an older build. Both are the adapter's problem,
 * and a caller that had to remember them would forget in one of the two places
 * it is used.
 */
export interface PreferenceStore {
  /** Collapsed panes within one view. Grouped rather than one flat list
   *  because two views now remember a layout, and a single list means the
   *  session view's next write erases the research view's -- the names do not
   *  collide, but each writer replaces the whole list. */
  collapsedPanes(group: string): readonly string[]
  setCollapsedPanes(group: string, names: readonly string[]): void
}
