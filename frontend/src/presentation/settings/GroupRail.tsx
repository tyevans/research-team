import clsx from 'clsx'

/** The group names, down the left, scrolling the page.
 *
 * **A rail, not tabs.** Tabs would make this several documents; it should be
 * one scannable page that the browser's own find works over, because "which
 * knob was it" is how people actually arrive here — and find across a tab
 * panel that is not mounted finds nothing. The rail is navigation within one
 * document, which is what `<nav>` and a list of in-page links say.
 *
 * `sticky top-0` is measured against the scroll container rather than the
 * viewport, so the console header does not need subtracting here. That is
 * checked in `settings-rail.browser.test.tsx` rather than asserted from the
 * markup, for the usual reason: jsdom lays nothing out, so a sticky element
 * that is not sticking looks exactly like one that is.
 */
export const GroupRail = ({
  groups,
  active,
  overrideCounts,
  onSelect,
}: {
  groups: readonly string[]
  active: string | null
  /** How many settings in each group this scope has overridden. Shown because
   *  it is the answer to the question that brings most people here — "what did
   *  we change" — and shown *per group* rather than only as a page total,
   *  which would tell them a number without telling them where to look. */
  overrideCounts: ReadonlyMap<string, number>
  onSelect: (group: string) => void
}) => (
  <nav aria-label="Settings groups" className="sticky top-0 flex flex-col gap-1 self-start py-3">
    {groups.map((group) => {
      const count = overrideCounts.get(group) ?? 0
      return (
        <button
          key={group}
          type="button"
          aria-current={group === active ? 'true' : undefined}
          onClick={() => onSelect(group)}
          className={clsx(
            'lay-ring-inward cursor-pointer rounded-md bg-transparent px-2 py-1 text-left text-sm',
            group === active ? 'text-accent' : 'text-fg-dim hover:text-fg',
          )}
        >
          {group}
          {count > 0 ? <span className="ml-2 font-mono text-xs text-fg-faint">{count}</span> : null}
        </button>
      )
    })}
  </nav>
)
