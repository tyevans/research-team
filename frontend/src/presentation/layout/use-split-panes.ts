import { useCallback, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { useContainer } from '@app/container-context.tsx'

/** A `Split`'s half of its own layout: which panes are folded, remembering it
 *  across reloads, and the sentence a refusal earns.
 *
 * `Split` owns the sizing and the last-open rule; this owns persistence and
 * the toast. The division is deliberate: a layout primitive that reached for a
 * toast store would be application coupling in a component whose whole claim
 * is that it renders from props.
 *
 * Parameterised by `group` rather than written once per view, because it had
 * already been written once per view. The session view's copy and the course
 * view's would have been the same twenty lines differing in one string --
 * which is the shape of the four fold implementations this migration exists to
 * remove, and it would have been embarrassing to add a fifth while deleting
 * them. The group is what keeps two views' layouts apart: one shared key meant
 * the second writer erased the first's.
 *
 * The refusal cannot be persisted, and that is structural rather than a rule
 * to remember. `Split` calls `onRefuse` *instead of* `onCollapsedChange`, so
 * the write is not on that path at all -- where the hook this replaces had a
 * `return current` inside an updater that also held the write, one edit away
 * from storing an all-closed layout that a reload would come back to.
 */
export const useSplitPanes = (group: string) => {
  const { preferences } = useContainer()
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(
    () => new Set(preferences.collapsedPanes(group)),
  )

  const onCollapsedChange = useCallback(
    (next: ReadonlySet<string>) => {
      preferences.setCollapsedPanes(group, [...next])
      setCollapsed(next)
    },
    [preferences, group],
  )

  const onRefuse = useCallback(() => {
    notify('At least one pane has to stay open.', 'bad')
  }, [])

  return { collapsed, onCollapsedChange, onRefuse }
}
