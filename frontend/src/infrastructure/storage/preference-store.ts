import type { PreferenceStore } from '@application/ports/preferences.ts'

/* One key per view. The old single `rt.collapsedPanes` key is left behind
   rather than migrated: it holds a pane layout, the project is pre-release,
   and the cost of losing it is that one reader's panes open once. */
const collapsedKey = (group: string) => `rt.collapsedPanes.${group}`

/** `localStorage`, with every way it fails absorbed here.
 *
 * It throws outright in private mode and in a browser with storage disabled,
 * and it can hold junk left behind by an older build. Neither is worth failing
 * a page over: a reader who loses their pane layout has lost a preference, and
 * a reader who gets a blank console has lost the tool.
 */
export class LocalPreferenceStore implements PreferenceStore {
  collapsedPanes(group: string): readonly string[] {
    try {
      const raw = window.localStorage.getItem(collapsedKey(group))
      const parsed: unknown = raw ? JSON.parse(raw) : []
      if (!Array.isArray(parsed)) return []
      return parsed.filter((name): name is string => typeof name === 'string')
    } catch {
      return []
    }
  }

  setCollapsedPanes(group: string, names: readonly string[]): void {
    try {
      window.localStorage.setItem(collapsedKey(group), JSON.stringify(names))
    } catch {
      // Not worth failing over: the layout still applies for this page's life.
    }
  }
}

/** For tests and for a headless render: remembers nothing, fails at nothing. */
export class InMemoryPreferenceStore implements PreferenceStore {
  private panes = new Map<string, readonly string[]>()

  collapsedPanes(group: string): readonly string[] {
    return this.panes.get(group) ?? []
  }

  setCollapsedPanes(group: string, names: readonly string[]): void {
    this.panes.set(group, names)
  }
}
