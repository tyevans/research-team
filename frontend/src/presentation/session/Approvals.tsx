import type { Approval, ApprovalDecision } from '@domain/approval/approval.ts'
import { safeJson } from '@domain/conversation/message.ts'
import type { ApprovalId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'

/** Gated calls, waiting on a person.
 *
 * A card can be answered here, in the REPL, or in another tab — whichever gets
 * there first. `ApprovalSettled`, not this click handler, is what takes it
 * down; that is what makes the other two paths work too, instead of only the
 * one this tab drove. */
export const Approvals = ({
  approvals,
  deciding,
  onDecide,
}: {
  approvals: ReadonlyMap<ApprovalId, Approval>
  deciding: ApprovalId | null
  onDecide: (approval: Approval, decision: ApprovalDecision) => void
}) => (
  <div className="approvals">
    {[...approvals.values()].map((approval) => (
      <div key={approval.id} className="approval">
        <div className="approval-head">
          <span>wants to run</span>
          <b>{approval.toolName}</b>
        </div>
        {approval.description ? (
          <div className="approval-desc">{approval.description}</div>
        ) : null}
        <div className="approval-args">{safeJson(approval.args)}</div>
        <div className="approval-actions">
          <Button
            tone="accent"
            disabled={deciding === approval.id}
            onClick={() => onDecide(approval, 'approve')}
          >
            Approve
          </Button>
          <Button
            tone="quiet"
            disabled={deciding === approval.id}
            onClick={() => onDecide(approval, 'reject')}
          >
            Reject
          </Button>
        </div>
      </div>
    ))}
  </div>
)
