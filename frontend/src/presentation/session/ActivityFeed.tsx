import type { SessionStore } from '@application/session/session-store.ts'
import { activityBody } from '@domain/activity/activity.ts'
import { TurnState } from '@domain/session/turn.ts'

/** Provisional content for the turn in flight.
 *
 * Gated on the turn state as well as on having entries: the tab that *sent* the
 * turn tracks it as `sending` while a tab only watching tracks it as
 * `watching`, and a bubble outliving both is one nothing would ever clear. */
export const ActivityFeed = ({ store }: { store: SessionStore }) => {
  const turn = store((state) => state.turn)
  const activity = store((state) => state.activity)

  if (!TurnState.isBusy(turn) || activity.size === 0) return null

  return (
    <div className="activity">
      {[...activity.values()].map((entry) => (
        <div key={entry.messageId} className={`provisional provisional-${entry.kind}`}>
          <div className="provisional-tag">in progress — not yet recorded</div>
          <div className="provisional-body">{activityBody(entry)}</div>
        </div>
      ))}
    </div>
  )
}
