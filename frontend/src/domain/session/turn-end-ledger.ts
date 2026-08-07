/** What this connection already knows about turns that have ended.
 *
 * This exists because the backend does two things that are not one thing: it
 * clears its "current turn" tracker, and it emits the `TurnCompleted` /
 * `TurnFailed` event. Between those two steps — and the lag is server-side, not
 * a narrow in-flight window — `GET /turns/current` answers `running: true`
 * about a turn this connection has *already seen end*. Trusting that answer
 * resurrects a finished turn and leaves the composer disabled with nothing left
 * to correct it.
 *
 * A turn-end frame, by contrast, is strictly ordered on this connection and can
 * never be stale. So the frames are the authority and every GET is checked
 * against them, never the other way around.
 *
 * Two independent checks, because each catches a case the other misses:
 *
 *  - `sequence` counts turn-ends seen. A GET whose answer arrives after a
 *    turn-end that was not there when it was sent is in flight across an
 *    ending, and its positive answer is discarded. Cheap, and catches the
 *    genuine in-flight race.
 *
 *  - `lastEndedAt` is the server clock reading of the most recent ending. A GET
 *    naming a turn that *started* no later than that is describing a turn this
 *    connection watched end, regardless of when the request was sent. This is
 *    the check that covers the server-side lag, which the sequence alone
 *    cannot: `loadSession()` is called immediately after reconciling a turn
 *    end, so the sequence does not change across that request at all.
 *
 * Timestamps, not turn indices. A `TurnFailed` carries `turn_index + 1` while
 * the session deliberately does not advance its own index on failure ("the turn
 * did not happen"), so a retry after a failure computes the *same* index again.
 * Comparing indices made one failed turn suppress every retry that followed it,
 * forever. A retry always starts strictly after the failure it followed, so
 * comparing start times tells a genuine new turn from a straggler however many
 * times the index repeats.
 *
 * Only positive answers are ever downgraded. `running: false` is always safe.
 */
export class TurnEndLedger {
  private constructor(
    readonly sequence: number,
    readonly lastEndedAt: number | null,
  ) {}

  static empty(): TurnEndLedger {
    return new TurnEndLedger(0, null)
  }

  /** Record a turn-end frame. `occurredAt` is the server's clock, and must be:
   *  it is compared against a `started_at` from that same clock. */
  recordEnding(occurredAt: string | null | undefined, now: number): TurnEndLedger {
    const at = occurredAt ? Date.parse(occurredAt) : Number.NaN
    return new TurnEndLedger(this.sequence + 1, Number.isNaN(at) ? now : at)
  }

  /** Whether a `running: true` answer describes a turn that is genuinely live.
   *
   * @param sequenceAtRequest the ledger's sequence when the request was sent.
   * @param startedAt the turn's `started_at`, as the server reported it.
   */
  trustsRunning(sequenceAtRequest: number, startedAt: string | null | undefined): boolean {
    if (this.sequence !== sequenceAtRequest) return false
    if (this.lastEndedAt === null) return true
    const started = startedAt ? Date.parse(startedAt) : Number.NaN
    if (Number.isNaN(started)) return true
    return started >= this.lastEndedAt
  }
}
