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
   * A tool gate allows approve/edit/reject; a stage gate also allows respond.
   * The list is per-gate rather than per-type, so offering the union of both
   * would post a `type` the server rejects on half the cards. */
  readonly allowedDecisions: readonly ApprovalDecision[]
  /** Null for a tool gate, which carries no review context at all. */
  readonly context: GateContext | null
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

/** One reviewer check against a stage's output.
 *
 * `severity` is a plain string rather than a union: it is authored by the
 * reviewer prompts, and a new level appearing server-side should widen what
 * the card displays, not make the card fail to render. */
export interface GateFinding {
  readonly check: string
  readonly severity: string
  readonly message: string
  readonly cites: readonly string[]
  readonly suggestedEdit: string | null
}

/** What a stage gate knows about the work it is gating. */
export interface GateContext {
  readonly stage: string
  readonly findingsArtifact: string
  readonly artifactPaths: readonly string[]
  readonly blocked: boolean
  readonly artifactsReviewed: number
  readonly linksReviewed: number
  readonly unimplementedChecks: readonly string[]
  readonly unreadableArtifacts: readonly string[]
  readonly findings: readonly GateFinding[]
}
