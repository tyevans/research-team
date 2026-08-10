/** What has been dispatched at one topic, and where it got to.
 *
 * Like `SeedingRun` and unlike `Extraction`, this is not folded from a stream
 * of notes — the server has nothing durable to fold either (see `dispatch.py`)
 * — so each frame *is* the whole state of one dispatch and the newest one for
 * a topic replaces the last.
 *
 * Unlike `SeedingRun`, there can be several at once: one running and any
 * number queued, all on the same project. That is why `topicId` is on the
 * model rather than implied by which pane is showing it — a project's
 * dispatches are keyed by topic, and a row has to be able to find its own.
 */
export type DispatchStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

export interface Dispatch {
  readonly dispatchId: string
  readonly topicId: string
  /** What it was asked to do. `understanding` is the only action this build
   *  runs; typed as a string because a server that grows `lesson` should show
   *  it by name rather than fail validation and blank the row. */
  readonly action: string
  readonly status: DispatchStatus
  /** The topic's question, composed server-side so the landing-page roster
   *  and this row say the same words. */
  readonly question: string | null
  /** Where it is in the queue, 1-based, or `null` when it is not queued.
   *  Recomputed by the server on every read rather than fixed at press time,
   *  so this moves as the queue drains. */
  readonly position: number | null
  /** The file it wrote, once done. `null` until then, and on failure. */
  readonly path: string | null
  /** The session that wrote the file — the only handle a viewer has on it. */
  readonly sessionId: string | null
  /** Why it failed. `null` on anything but `failed`. */
  readonly detail: string | null
}

/** Whether this dispatch is still going to produce something.
 *
 * One predicate rather than each caller comparing against two literals: the
 * set grows when `research` lands (which will add no status, but will add
 * rows that sit in `queued` far longer), and a caller that had inlined
 * `status === 'running'` would quietly stop showing queued work.
 */
export const isPending = (dispatch: Dispatch): boolean =>
  dispatch.status === 'queued' || dispatch.status === 'running'

/** Everything a project has dispatched, as the topic list needs to read it.
 *
 * Keyed by topic rather than a flat list, because every read of this is "what
 * is happening to *this* row" — forty rows each scanning a list would be
 * forty linear searches per render.
 */
export const byTopic = (dispatches: readonly Dispatch[]): ReadonlyMap<string, Dispatch> => {
  const map = new Map<string, Dispatch>()
  for (const dispatch of dispatches) {
    // Last write wins, and the caller controls the order: the catch-up route
    // returns finished dispatches first and the running one after, so a topic
    // dispatched twice shows what is happening now rather than how the last
    // one went.
    map.set(dispatch.topicId, dispatch)
  }
  return map
}
