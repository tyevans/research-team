/** Reporting what the user did, for a log nobody reads back yet.
 *
 * A port because there are two delivery mechanisms with genuinely different
 * guarantees, and the difference belongs in the interface rather than inside
 * one method that picks. Everything else about this feature -- what is worth
 * recording, when to flush -- is application logic and lives above this line.
 */

export interface InteractionEvent {
  readonly kind: string
  readonly browser_session_id: string
  readonly install_id: string
  readonly seq: number
  readonly view: string
  readonly occurred_at: string
  readonly project_id?: string | null
  readonly session_id?: string | null
  readonly payload: Readonly<Record<string, unknown>>
}

export interface InteractionSink {
  /** Deliver a batch while the page is alive. Rejects on transport failure;
   *  the caller drops the batch rather than retrying, because this data is
   *  droppable by design and a retry queue would make late arrival a
   *  permanent property of the log. */
  send(events: readonly InteractionEvent[]): Promise<void>

  /** Deliver a batch while the page is going away.
   *
   *  `sendBeacon` rather than `fetch`, because an in-flight fetch is
   *  cancelled on unload and the tail of every session -- where friction
   *  lives -- would be the part that never arrives.
   *
   *  Returns nothing on purpose: the browser reports only whether it queued
   *  the payload, never whether it was received, so a promise here would
   *  promise something unknowable. */
  sendOnUnload(events: readonly InteractionEvent[]): void
}
