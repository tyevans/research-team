import type { PreferenceStore } from '@application/ports/preferences.ts'

const COLLAPSED_PANES = 'rt.collapsedPanes'

/** `localStorage`, with every way it fails absorbed here.
 *
 * It throws outright in private mode and in a browser with storage disabled,
 * and it can hold junk left behind by an older build. Neither is worth failing
 * a page over: a reader who loses their pane layout has lost a preference, and
 * a reader who gets a blank console has lost the tool.
 */
export class LocalPreferenceStore implements PreferenceStore {
  collapsedPanes(): readonly string[] {
    try {
      const raw = window.localStorage.getItem(COLLAPSED_PANES)
      const parsed: unknown = raw ? JSON.parse(raw) : []
      if (!Array.isArray(parsed)) return []
      return parsed.filter((name): name is string => typeof name === 'string')
    } catch {
      return []
    }
  }

  setCollapsedPanes(names: readonly string[]): void {
    try {
      window.localStorage.setItem(COLLAPSED_PANES, JSON.stringify(names))
    } catch {
      // Not worth failing over: the layout still applies for this page's life.
    }
  }
}

/** For tests and for a headless render: remembers nothing, fails at nothing. */
export class InMemoryPreferenceStore implements PreferenceStore {
  private panes: readonly string[] = []

  collapsedPanes(): readonly string[] {
    return this.panes
  }

  setCollapsedPanes(names: readonly string[]): void {
    this.panes = names
  }
}
