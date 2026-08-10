import { useCallback, useState } from 'react'

import { useContainer } from '@app/container-context.tsx'

/** Which view's layout this is. The session view remembers its own under a
 *  different group; one shared key meant the second writer erased the first's. */
const GROUP = 'research'

/** The rail's three panes, in the order they appear down it.
 *
 * The ids double as the `Pane` ids and as the strings written to preferences,
 * which is what makes a stored layout survive this migration: `RailPane` wrote
 * exactly these three names under exactly this group, so a reader who folded
 * their documents pane last week still finds it folded.
 */
export const RESEARCH_RAIL_PANES = ['seeding', 'topics', 'documents'] as const

export type ResearchRailPane = (typeof RESEARCH_RAIL_PANES)[number]

/** Which rail panes are folded, remembered across reloads.
 *
 * One hook holding one set, rather than `RailPane`'s hook-per-pane. That
 * version had three independent writers to one stored list and needed a
 * re-read inside every write to stop the second fold erasing the first --
 * a comment in the file says so. With the set owned once there is only one
 * writer and the dance is unnecessary rather than merely documented.
 *
 * No "at least one must stay open" rule, unlike `useSessionPanes`. `Pane`
 * collapsed to a `strip` leaves its head -- title and toggle -- on screen, so
 * every fold remains reversible from what is still visible. That is the
 * precondition `split-tracks.ts` names for the permissive arm being safe, and
 * the reason `Split`'s unconditional refusal is not wanted here.
 */
export const useResearchPanes = () => {
  const { preferences } = useContainer()
  const [folded, setFolded] = useState<ReadonlySet<string>>(
    () => new Set(preferences.collapsedPanes(GROUP)),
  )

  const toggle = useCallback(
    (id: string) => {
      setFolded((current) => {
        const next = new Set(current)
        if (!next.delete(id)) next.add(id)
        preferences.setCollapsedPanes(GROUP, [...next])
        return next
      })
    },
    [preferences],
  )

  return { folded, toggle }
}
