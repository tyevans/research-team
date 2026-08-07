/** Reader preferences that outlive a page load.
 *
 * A port rather than a direct `localStorage` call because storage throws in
 * private mode and in a browser with it disabled, and because the console must
 * survive junk left behind by an older build. Both are the adapter's problem,
 * and a caller that had to remember them would forget in one of the two places
 * it is used.
 */
export interface PreferenceStore {
  collapsedPanes(): readonly string[]
  setCollapsedPanes(names: readonly string[]): void
}
