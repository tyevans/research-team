import type { ActivityEntry } from '@domain/activity/activity.ts'
import type { Approval } from '@domain/approval/approval.ts'
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
