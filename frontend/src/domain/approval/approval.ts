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
}

/** langchain's vocabulary, not ours — `accept` is not a valid decision type. */
export type ApprovalDecision = 'approve' | 'reject'
