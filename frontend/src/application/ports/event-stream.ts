import type { ActivityEntry } from '@domain/activity/activity.ts'
import type { Approval } from '@domain/approval/approval.ts'
import type { Dispatch } from '@domain/research/dispatch.ts'
import type { SeedingRun } from '@domain/research/seeding.ts'
import type { LogEntry } from '@domain/session/log-entry.ts'
import type { ApprovalId, SessionId, TopicId } from '@domain/shared/identifier.ts'

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
  /** A dispatch was queued, started, finished or failed.
   *
   * Decoded rather than routed raw, for `seeding`'s reason: `DispatchQueue`
   * hands back one flat frame that already is the full domain model. Like
   * seeding and unlike `topic`, it carries no feed position — nothing about a
   * dispatch is appended to the log, so `Last-Event-ID` cannot replay these
   * and a reconnecting tab refetches `/projects/{id}/dispatch` instead.
   *
   * `projectId` rides alongside `dispatch` rather than inside it because
   * `Dispatch` is also what the catch-up route hands back, which is not
   * project-addressed once it is in a per-project query cache. */
  | { readonly kind: 'dispatch'; readonly projectId: string; readonly dispatch: Dispatch }
  /** A topic was opened or moved.
   *
   * A durable log entry, unlike `extraction` and `seeding` beside it -- it
   * carries a feed position, so a reconnect replays it. It is still not a
   * `log` frame, because a topic is not a session: its aggregate id under
   * `sessionId` would have the tree and the session views refetching a
   * session that does not exist.
   *
   * No project id, matching the server (`topic_change` in `presenters.py`
   * says why): only the creation event knows one. A subscriber scopes by the
   * project it is already showing. */
  | { readonly kind: 'topic'; readonly topicId: TopicId; readonly change: string }
  /** The project's knowledge graph moved -- an extraction landed, or entities
   * merged.
   *
   * Project-addressed and durable, which no other frame here manages both of:
   * it carries a feed position like a log frame, so a reconnect replays it,
   * *and* it says whose graph it is, because redstring writes tenant events
   * and a project is the tenant. A subscriber can therefore ignore another
   * project's extraction outright rather than re-reading its own graph to
   * discover nothing changed -- which matters more here than for a topic
   * list, because the read it saves is a whole graph.
   *
   * It carries no entities, only that some arrived. The pane re-reads the
   * graph route, which is the one description of what the graph is; folding a
   * payload into the drawing instead would give the page a second one, and
   * the two would disagree the moment consolidation merged anything. */
  | { readonly kind: 'graph'; readonly projectId: string; readonly change: string }
  /** A document was stored in, or dropped from, the project's corpus.
   *
   * Its own kind rather than a `graph` frame, even though one ingest emits
   * both: the document is stored *before* it is extracted (see
   * `_store_document`, which says why that order and not the other), so an
   * extraction that fails emits this and no graph frame at all. A documents
   * pane keyed to graph frames would go quiet on exactly the ingests whose
   * source a reader needs to find. */
  | { readonly kind: 'corpus'; readonly projectId: string; readonly change: string }

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
