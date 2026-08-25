/** What the console reads back out of the interaction log.
 *
 * The write side lives in `@application/ports/interaction-log.ts` and shares
 * none of these types on purpose: it describes an event on its way out of the
 * browser, before a server has stamped it, and this describes a row that came
 * back with `received_at`, a decoded payload and a store's idea of ordering.
 * One shared type would have to make every server-assigned field optional,
 * which is exactly the ambiguity the reader exists to remove.
 *
 * Hence `LoggedInteraction` rather than `InteractionEvent`: the two names
 * would collide across the two modules, and the collision would typecheck.
 *
 * Instants are `Date` here where the rest of this domain layer keeps ISO
 * strings. The reason is arithmetic: every pane over this data subtracts two
 * instants (last-event age, the gaps between events in a drill-down) or
 * compares them, and a layer of `Date.parse` at each call site is a layer of
 * places to forget. `InteractionFilters.since`/`until` stay strings, because
 * those go straight back out as query parameters and never get subtracted.
 */

import type {
  BrowserSessionId,
  InstallId,
  ProjectId,
  SessionId,
} from '@domain/shared/identifier.ts'

/** A count against a name, rather than a `Record<string, number>`.
 *
 * The server sends `kinds` covering every kind in its vocabulary, zeros
 * included, in vocabulary order -- and that order is the whole readability of
 * the pane. An object would hand the order to whatever `Object.keys` decides,
 * which for these non-numeric keys is insertion order today and is not a
 * guarantee anybody should be resting a rendered list on. An array says the
 * order is data.
 */
export interface KindCount {
  readonly kind: string
  readonly count: number
}

/** An event the projection could not process.
 *
 * Non-empty means interactions the browser reported are missing from the
 * table. Rendered only when non-empty: a red block that is usually absent is
 * readable, a green tick that is always present is not.
 */
export interface ProjectionFailure {
  readonly id: string
  readonly eventType: string
  readonly error: string
  readonly failedAt: Date | null
}

/** Is the instrument working.
 *
 * `collecting` is a fact about the recorder's environment variable, not about
 * the data: with collection off this answers 200 with an empty log and
 * `collecting: false`, which is what lets a reader tell "switched off" from
 * "broken". A log that is empty and collecting is a third state again.
 */
export interface InteractionLogHealth {
  readonly collecting: boolean
  readonly total: number
  /** `null` on an empty log -- a real state, not a missing value. */
  readonly firstAt: Date | null
  readonly lastAt: Date | null
  readonly kinds: readonly KindCount[]
  readonly failures: readonly ProjectionFailure[]
  readonly installCount: number
  readonly sessionCount: number
}

/** One interaction, as stored. */
export interface LoggedInteraction {
  readonly browserSessionId: BrowserSessionId
  readonly installId: InstallId
  readonly seq: number
  readonly kind: string
  readonly view: string
  readonly occurredAt: Date
  /** When the server took it. `null` for a row written before the column
   *  existed; the difference against `occurredAt` is the delivery lag. */
  readonly receivedAt: Date | null
  readonly projectId: ProjectId | null
  readonly sessionId: SessionId | null
  /** Everything specific to the kind, decoded. Read structurally by whatever
   *  renders the kind -- this layer has no opinion on it, because the shape
   *  differs per kind and enumerating fifteen of them here would put the
   *  vocabulary in two places. */
  readonly payload: Readonly<Record<string, unknown>>
}

/** One browser session, summarised. */
export interface BrowserSession {
  readonly browserSessionId: BrowserSessionId
  readonly installId: InstallId
  readonly startedAt: Date | null
  readonly endedAt: Date | null
  /** What arrived. Beside `maxSeq` on purpose: `seq` is the browser's own
   *  counter, so the two disagree exactly when delivery lost something, and
   *  that gap is the cheapest integrity check the transport has. */
  readonly eventCount: number
  readonly maxSeq: number
  readonly views: readonly string[]
  readonly projectIds: readonly ProjectId[]
  readonly kinds: readonly KindCount[]
}

export interface BrowserSessionPage {
  readonly sessions: readonly BrowserSession[]
  readonly total: number
}

export interface InteractionPage {
  readonly events: readonly LoggedInteraction[]
  /** The count under the same filters, never the page length. A reader who
   *  cannot tell 200-of-200 from 200-of-9000 cannot tell a filter that found
   *  everything from one that hit the cap. */
  readonly total: number
  readonly limit: number
  readonly offset: number
}

/** One view's traffic and how long people stayed. */
export interface ViewDwell {
  readonly view: string
  readonly entries: number
  /** Apart from `entries` because the difference is the count of views left
   *  by a route the page-hide flush did not catch. */
  readonly exits: number
  /** `null` when there is nothing to take a median of -- a view with entries
   *  and no exits. Not zero: zero is a real dwell and would read as a page
   *  nobody stayed on. */
  readonly dwellMsMedian: number | null
  readonly dwellMsP90: number | null
  /** Beside dwell and never subtracted from it: the consumer chooses. */
  readonly hiddenMsMedian: number | null
}

export interface EmptyResultPlace {
  readonly where: string
  readonly count: number
}

export interface FrictionSummary {
  readonly undone: number
  readonly retried: number
  readonly emptyResults: number
  readonly emptyByWhere: readonly EmptyResultPlace[]
  /** Searches close to the one immediately before them in the same browser
   *  session. A heuristic pointer to a stream worth reading, never a
   *  measurement. */
  readonly repeatSearches: number
}

export interface DecisionCount {
  readonly decision: string
  readonly count: number
}

export interface ApprovalSummary {
  readonly total: number
  /** `expanded_details == true`. **The name overstates it**, exactly as the
   *  server's own docstring says: it counts readers who opened Edit or
   *  Respond, so a careful reader who deliberates and then presses plain
   *  Approve records `false`. A floor on deliberation, never a count of who
   *  read carefully. */
  readonly expanded: number
  /** `null` when nothing was decided in the window. Medians throughout: one
   *  backgrounded tab produces a latency in the hours, and a mean over it
   *  says nothing about anybody. */
  readonly medianLatencyMs: number | null
  readonly medianLatencyMsExpanded: number | null
  readonly medianLatencyMsPlain: number | null
  readonly byDecision: readonly DecisionCount[]
}

export interface InteractionSummary {
  readonly byKind: readonly KindCount[]
  readonly byView: readonly ViewDwell[]
  readonly friction: FrictionSummary
  readonly approvals: ApprovalSummary
}
