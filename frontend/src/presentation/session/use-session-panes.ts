import { useCallback, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { useContainer } from '@app/container-context.tsx'
import type { Track } from '@presentation/layout/split-tracks.ts'

/** Which view's layout this is. The research rail remembers its own under a
 *  different group, and the two are different sets of panes -- one shared key
 *  meant the second writer erased the first's. */
const GROUP = 'session'

/** The session view's three columns, as data.
 *
 * These are the values that are **live today**, not the ones `panes.css`
 * declared: the hook wrote `grid-template-columns` inline and an inline style
 * outranks a stylesheet unconditionally, so `panes.css:73`'s
 * `minmax(300px, 1.05fr) minmax(320px, 1.5fr) minmax(300px, 1.15fr)` has never
 * taken effect on a wide screen. Confirmed in a browser rather than reasoned
 * about. Adopting it here would have been a silent 20px change to two columns
 * and a weight change to a third, arriving as a side effect of a refactor;
 * whether it is the better design is a separate question with a separate
 * argument, and it is not this change's to make.
 */
export const SESSION_TRACKS: readonly Track[] = [
  { id: 'timeline', min: 280, weight: 1.05 },
  { id: 'workspace', min: 320, weight: 1.5 },
  { id: 'conversation', min: 280, weight: 1.05 },
]

/** The session view's half of its pane layout: which panes are folded, and
 *  remembering that across reloads.
 *
 * `Split` owns the sizing and the last-open rule; this owns persistence and
 * the sentence a refusal earns. The division is deliberate: a layout primitive
 * that reached for a toast store would be application coupling in a component
 * whose whole claim is that it renders from props.
 *
 * The refusal cannot be persisted, and that is now structural rather than a
 * rule to remember. `Split` calls `onRefuse` *instead of* `onCollapsedChange`,
 * so the write is not on that path at all -- where the hook this replaces had
 * a `return current` inside an updater that also held the write, one edit away
 * from storing an all-closed layout that a reload would come back to.
 */
export const useSessionPanes = () => {
  const { preferences } = useContainer()
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(
    () => new Set(preferences.collapsedPanes(GROUP)),
  )

  const onCollapsedChange = useCallback(
    (next: ReadonlySet<string>) => {
      preferences.setCollapsedPanes(GROUP, [...next])
      setCollapsed(next)
    },
    [preferences],
  )

  const onRefuse = useCallback(() => {
    notify('At least one pane has to stay open.', 'bad')
  }, [])

  return { collapsed, onCollapsedChange, onRefuse }
}
