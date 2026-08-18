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
  /** Deliver a batch while the page is alive.
   *
   *  **Never rejects. An implementation absorbs its own transport failures
   *  and resolves anyway**, and the batch is simply lost -- this data is
   *  droppable by design, and a retry queue would make late arrival a
   *  permanent property of the log.
   *
   *  Stated as a requirement on implementations rather than left to each one,
   *  because the two halves shipped disagreeing: this line originally read
   *  "rejects on transport failure" while the only adapter swallowed every
   *  `ApiError`, which made the emitter's `try/catch` dead code against the
   *  shipped adapter and made a future adapter that *did* reject correct by
   *  the docs and a console-breaking bug in practice. Telemetry that breaks
   *  the console is far worse than telemetry that is missing, so the promise
   *  moved to match the adapter rather than the other way round. The
   *  emitter's catch stays as belt-and-braces for an implementation that
   *  breaks this promise. */
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
