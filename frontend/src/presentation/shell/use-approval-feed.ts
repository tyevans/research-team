import { useCallback, useEffect, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import type { Approval, ApprovalAnswer } from '@domain/approval/approval.ts'
import type { ApprovalId } from '@domain/shared/identifier.ts'
import { ApiError, errorMessage } from '@application/ports/errors.ts'
import { useContainer } from '@app/container-context.tsx'

import { useStream } from './StreamProvider.tsx'

/** Every gated call in the console, regardless of which page is open.
 *
 * **Deliberately not scoped by session**, which is the one thing that makes
 * this different from the session store's own approval state. An approval
 * blocks an agent until a person answers it, and the person is wherever they
 * are — on the landing page, on another session, on a project's course view.
 * Filtering by `sessionId` here would reproduce exactly the defect this
 * replaces: three call sites, each of which could only show you the approvals
 * belonging to the thing you were already looking at.
 *
 * **No HTTP at all, and no polling.** Both frames are already on the single
 * `EventSource`, and `ApprovalRegistry.listen` seeds every new listener with
 * whatever is already parked (it says why: these frames carry no feed
 * position, so `Last-Event-ID` cannot replay them). So a browser that connects
 * a moment after a call was gated is caught up by the connection itself. A
 * catch-up fetch here would be a second description of the same state, and the
 * two would disagree during the window it exists to close.
 */
export interface ApprovalFeed {
  readonly approvals: ReadonlyMap<ApprovalId, Approval>
  /** The one card with a decision in flight, or null. One at a time, matching
   *  the session store: two answers racing on one gate means one of them is
   *  answering something that is already settled. */
  readonly deciding: ApprovalId | null
  /** A property holding a function rather than a method, deliberately: the bar
   *  destructures this off the feed, and `@typescript-eslint/unbound-method`
   *  is right to reject that for a method — a plucked method loses its
   *  receiver. This one is a `useCallback` closure and has no receiver to
   *  lose, and saying so in the type is more honest than suppressing the rule
   *  at the call site. */
  readonly decide: (approval: Approval, answer: ApprovalAnswer) => void
}

export const useApprovalFeed = (): ApprovalFeed => {
  const container = useContainer()
  const stream = useStream()
  const [approvals, setApprovals] = useState<ReadonlyMap<ApprovalId, Approval>>(() => new Map())
  const [deciding, setDeciding] = useState<ApprovalId | null>(null)

  useEffect(
    () =>
      stream.onFrame((frame) => {
        if (frame.kind === 'approvalRequested') {
          const approval = frame.approval
          setApprovals((current) => new Map(current).set(approval.id, approval))
          return
        }
        if (frame.kind === 'approvalSettled') {
          const settled = frame.approvalId
          setApprovals((current) => {
            if (!current.has(settled)) return current
            const next = new Map(current)
            next.delete(settled)
            return next
          })
          setDeciding((current) => (current === settled ? null : current))
        }
      }),
    [stream],
  )

  // A reconnect is a *new* listener server-side, so it is re-seeded with
  // everything still parked. What it is not re-seeded with is the settlements
  // that happened while this tab was disconnected -- those frames carry no
  // position and are simply gone -- so anything held from before the drop is
  // unverifiable. Emptying and letting the seed refill is the only thing here
  // that cannot show a card for a gate somebody already answered; the cost is
  // a visible flicker on reconnect, and the alternative is a stale card whose
  // buttons all 404.
  useEffect(() => stream.onReconnect(() => setApprovals(new Map())), [stream])

  const decide = useCallback(
    (approval: Approval, answer: ApprovalAnswer) => {
      if (deciding) return
      setDeciding(approval.id)
      void (async () => {
        try {
          await container.approvals.decide(approval.sessionId, approval.id, answer)
        } catch (error) {
          // A 404 means somebody else already answered it; `ApprovalSettled`
          // will have cleared the card, so there is nothing left to undo.
          if (!(error instanceof ApiError && error.isNotFound)) {
            notify(`Could not record decision: ${errorMessage(error)}`, 'bad')
          }
        } finally {
          setDeciding((current) => (current === approval.id ? null : current))
        }
      })()
    },
    [container, deciding],
  )

  return { approvals, deciding, decide }
}
