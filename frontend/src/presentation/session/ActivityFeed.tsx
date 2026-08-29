import type { SessionStore } from '@application/session/session-store.ts'
import { activityBody, activityMessage } from '@domain/activity/activity.ts'
import { TurnState } from '@domain/session/turn.ts'

import { ToolResult } from './shapes/ToolResult.tsx'

/** Provisional content for the turn in flight.
 *
 * Gated on the turn state as well as on having entries: the tab that *sent* the
 * turn tracks it as `sending` while a tab only watching tracks it as
 * `watching`, and a bubble outliving both is one nothing would ever clear.
 *
 * **The per-card `in progress — not yet recorded` tag is deleted, and that is a
 * design decision rather than tidying.** Repeated once per card it stopped
 * being read at all, which is the opposite of what a provisional marker is for.
 * Phase is carried by position now — everything above the live edge is settled
 * by virtue of being above it — plus a pulse on the row's glyph and a shimmer
 * under prose still arriving. */
export const ActivityFeed = ({ store }: { store: SessionStore }) => {
  const turn = store((state) => state.turn)
  const activity = store((state) => state.activity)

  if (!TurnState.isBusy(turn) || activity.size === 0) return null

  return (
    <div className="activity stream">
      {[...activity.values()].map((entry) => (
        <div key={entry.messageId} className={`provisional provisional-${entry.kind}`}>
          <ToolResult
            message={activityMessage(entry)}
            phase="live"
            // The caller's own markup, unchanged, so a message with no
            // artifact renders byte for byte what it renders today.
            fallback={<div className="provisional-body">{activityBody(entry)}</div>}
          />
          {/* Only where prose is genuinely still accumulating. `text` is the
              delta accumulator, and it is null on a whole-message entry --
              which is exactly the entry that has nothing more coming. */}
          {entry.text ? <div className="stream-shim" aria-hidden="true" /> : null}
        </div>
      ))}
    </div>
  )
}
