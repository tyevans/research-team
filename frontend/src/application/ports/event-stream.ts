import type { ActivityEntry } from '@domain/activity/activity.ts'
import type { Approval } from '@domain/approval/approval.ts'
import type { SeedingRun } from '@domain/research/seeding.ts'
import type { LogEntry } from '@domain/session/log-entry.ts'
import type { ApprovalId, SessionId } from '@domain/shared/identifier.ts'

/** What arrives over the live feed, as three genuinely different things.
 *
 * They ride one connection and are not one kind of message, which the previous
 * implementation discovered by having to re-check at the top of its handler.
 * A log frame is a durable record with a feed position; an approval frame and
 * an activity frame carry no position at all and cannot be replayed by
 * `Last-Event-ID`. Making that a type distinction is what lets the reconnect
 * logic state its own rule: resume the log from the cursor, and reconcile the
 * other two by asking.
 */
export type FeedFrame =
  | { readonly kind: 'log'; readonly sessionId: SessionId; readonly entry: LogEntry }
  | { readonly kind: 'approvalRequested'; readonly approval: Approval }
  | {
      readonly kind: 'approvalSettled'
      readonly sessionId: SessionId
      readonly approvalId: ApprovalId
    }
  | { readonly kind: 'activity'; readonly entry: ActivityEntry }
  /** Extraction progress, carried as the payload that arrived rather than as a
   *  mapped object.
   *
   *  The odd one out, deliberately. Every other frame here is addressed to a
   *  session and belongs to the session tree; this one is addressed to a
   *  *project* and is read by a per-project store that folds the frames
   *  itself. Routing the payload rather than a decoded frame keeps that
   *  folding — and the "is this my project?" test it turns on — in the one
   *  place that knows which project is on screen. */
  | { readonly kind: 'extraction'; readonly payload: unknown }
  /** A seeding run's status, decoded rather than routed raw.
   *
   * Unlike extraction, `SeedingActivity` hands back one flat frame that
   * already is the full domain model -- there is no note to fold, just the
   * one status a run is currently at -- so this is validated and mapped here
   * like an approval or activity frame. `projectId` rides alongside `run`
   * rather than inside it because `SeedingRun` is the read model `SeedPanel`
   * also gets from the catch-up route, which is not project-addressed once
   * it is in a per-project query cache. */
  | { readonly kind: 'seeding'; readonly projectId: string; readonly run: SeedingRun }

export type ConnectionState = 'connecting' | 'open' | 'down'

export interface EventStreamListener {
  onFrame(frame: FeedFrame): void
  onConnectionState(state: ConnectionState): void
  /** Fired once per successful reconnect.
   *
   * `resumable` is true when the connection had a cursor to send back, so the
   * server replayed the gap as ordinary log frames and only the position-less
   * channels need reconciling. False means this connection dropped before its
   * first frame and the server cannot place it — everything needs a resync. */
  onReconnect(resumable: boolean): void
}

export interface EventStream {
  connect(listener: EventStreamListener): void
  disconnect(): void
}
