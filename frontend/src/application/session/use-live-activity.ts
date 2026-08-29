import { useMemo } from 'react'

import { activityEntries, type ActivityEntry } from '@domain/activity/activity.ts'
import { TurnState } from '@domain/session/turn.ts'

import type { SessionStore } from './session-store.ts'

const NONE: readonly ActivityEntry[] = []

/** The turn in flight, or nothing.
 *
 * Gated on the turn state as well as on the buffer having entries, and that is
 * the whole reason this is a shared hook rather than two `store(...)` calls at
 * the call sites: the tab that *sent* the turn tracks it as `sending` while a
 * tab only watching tracks it as `watching`, so "is a turn running" is a
 * question with two right answers and one place to ask it. Entries surviving
 * the turn they belong to is the failure this prevents — a bubble nothing
 * would ever clear, because the frame that would have replaced it is not
 * coming.
 *
 * Memoised because the result is a prop that `Conversation` lists as an effect
 * dependency: `activityEntries` builds a fresh array from the buffer, so an
 * unmemoised call would hand a new identity to a stick-to-bottom effect on
 * every render of the whole session view, not on every frame.
 */
export const useLiveActivity = (store: SessionStore): readonly ActivityEntry[] => {
  const turn = store((state) => state.turn)
  const activity = store((state) => state.activity)
  const busy = TurnState.isBusy(turn)

  return useMemo(
    () => (busy && activity.size > 0 ? activityEntries(activity) : NONE),
    [busy, activity],
  )
}
