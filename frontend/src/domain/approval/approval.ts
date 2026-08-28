import type { ApprovalId, SessionId } from '../shared/identifier.ts'

/** A gated tool call, parked until a person answers it.
 *
 * It can be answered here, in the REPL, or in another tab — whichever gets
 * there first. That is why `ApprovalSettled` and not a click handler is what
 * clears a card: settling is the fact, and deciding is only one of three ways
 * to cause it.
 */
export interface Approval {
  readonly id: ApprovalId
  readonly sessionId: SessionId
  readonly toolName: string
  readonly description: string | null
  readonly args: unknown
  /** Which of the four the server will accept for *this* gate, and only these.
   *
   * Per-gate rather than per-type, so offering the union of what any gate might
   * accept would post a `type` the server rejects on half the cards. */
  readonly allowedDecisions: readonly ApprovalDecision[]
}

/** langchain's vocabulary, not ours — `accept` is not a valid decision type. */
export type ApprovalDecision = 'approve' | 'edit' | 'reject' | 'respond'

/** A decision plus what that decision needs to mean anything.
 *
 * `edit` without `editedArgs` and `respond` without `message` are both
 * degenerate — the server takes the answer and has nothing to apply — so the
 * payload travels with the decision rather than beside it. Both stay optional
 * because `approve` and `reject` carry neither. */
export interface ApprovalAnswer {
  readonly decision: ApprovalDecision
  readonly editedArgs?: unknown
  readonly message?: string
}
