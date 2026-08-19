import { useCallback, useEffect, useRef, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import type { Approval, ApprovalAnswer } from '@domain/approval/approval.ts'
import type { ApprovalId } from '@domain/shared/identifier.ts'
import { ApiError, errorMessage } from '@application/ports/errors.ts'
import { useContainer } from '@app/container-context.tsx'
import { useInteractionLog } from '@app/interaction-log-provider.tsx'

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
  readonly decide: (approval: Approval, answer: ApprovalAnswer, expandedDetails: boolean) => void
}

export const useApprovalFeed = (): ApprovalFeed => {
  const container = useContainer()
  const stream = useStream()
  const log = useInteractionLog()
  const [approvals, setApprovals] = useState<ReadonlyMap<ApprovalId, Approval>>(() => new Map())
  const [deciding, setDeciding] = useState<ApprovalId | null>(null)

  // When each pending approval was first seen, for `ApprovalDecided.latency_ms`
  // -- the click-through-versus-deliberation distinction `direction.md` §3
  // turns on. A ref, not state: nothing on screen reads it, so putting it in
  // state would be a render the timestamp itself never causes.
  //
  // `performance.now()` throughout this hook, matching `dwell.ts` and the
  // design's rule for durations: monotonic, so a system clock moved mid-
  // session cannot produce a negative or absurd one. It shipped on
  // `Date.now()`, and approvals are the *most* exposed measurement rather
  // than the least -- they live for minutes to hours by the field's own
  // docstring, so the window in which a clock change can land is the widest
  // in the log, and `latency_ms` is an `int` with no lower bound. Every value
  // here is differenced and never displayed, so the epoch is irrelevant;
  // rounded at the emission site because the domain field is an `int` and
  // pydantic refuses a fractional one, which `Date.now()` never produced.
  const shownAt = useRef<Map<ApprovalId, number>>(new Map())

  // Backgrounded time, accumulated for the tab's whole life, and what each
  // approval's total stood at when it was first shown. The difference is that
  // card's `hidden_ms`.
  //
  // Kept here rather than read off `DwellTracker`: dwell's accumulator resets
  // on every view change, and an approval outlives the view it appeared on --
  // that is the point of a feed that is not scoped by session. Two
  // accumulators over the same `visibilitychange` is duplication, and the
  // alternative is worse: an approval answered after navigating twice would
  // get whichever view's hidden time happened to be current.
  const hiddenMs = useRef(0)
  const hiddenSince = useRef<number | null>(null)
  const hiddenAtShown = useRef<Map<ApprovalId, number>>(new Map())

  const hiddenTotal = () =>
    hiddenMs.current + (hiddenSince.current === null ? 0 : performance.now() - hiddenSince.current)

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        // Guarded both ways for `dwell.ts`'s measured reason: overwriting
        // `hiddenSince` on a repeated hide silently discards the interval
        // already accumulating.
        if (hiddenSince.current !== null) return
        hiddenSince.current = performance.now()
        return
      }
      if (hiddenSince.current === null) return
      hiddenMs.current += performance.now() - hiddenSince.current
      hiddenSince.current = null
    }
    // A tab that is already hidden when this mounts is hidden from now, not
    // from zero -- a background tab restored by the browser on startup is the
    // ordinary way to reach that state.
    if (document.visibilityState === 'hidden') hiddenSince.current = performance.now()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  useEffect(
    () =>
      stream.onFrame((frame) => {
        if (frame.kind === 'approvalRequested') {
          const approval = frame.approval
          setApprovals((current) => new Map(current).set(approval.id, approval))
          if (!shownAt.current.has(approval.id)) {
            shownAt.current.set(approval.id, performance.now())
            hiddenAtShown.current.set(approval.id, hiddenTotal())
          }
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
          shownAt.current.delete(settled)
          hiddenAtShown.current.delete(settled)
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
  useEffect(
    () =>
      stream.onReconnect(() => {
        setApprovals(new Map())
        // The re-seed that follows is this tab seeing every parked approval
        // again; without clearing this, a card re-shown after a long
        // disconnect would report a `latency_ms` measured from before the
        // gap, which is not when *this* tab's reader started looking at it.
        shownAt.current.clear()
        hiddenAtShown.current.clear()
      }),
    [stream],
  )

  const decide = useCallback(
    (approval: Approval, answer: ApprovalAnswer, expandedDetails: boolean) => {
      if (deciding) return
      setDeciding(approval.id)
      const shown = shownAt.current.get(approval.id)
      const hiddenWhenShown = hiddenAtShown.current.get(approval.id) ?? 0
      void (async () => {
        try {
          await container.approvals.decide(approval.sessionId, approval.id, answer)
          // `latency_ms` is required, non-optional, in the domain schema --
          // there is no honest "unknown" value to put in it. If this tab
          // never saw the frame that would have started the clock (a settle
          // racing a mount, or a reconnect landing between request and
          // decision -- both real and both rare), the kind is skipped
          // entirely rather than reported with a fabricated zero, which is
          // the exact confident-wrong-value failure the brief calls out.
          if (shown !== undefined) {
            log.record('ApprovalDecided', {
              decision: answer.decision,
              latency_ms: Math.round(performance.now() - shown),
              // Reported alongside `latency_ms` rather than subtracted from
              // it, following `ViewExited`'s precedent so the consumer
              // chooses. Without it the click-through/deliberation split --
              // the entire reason this kind exists -- cannot tell twelve
              // seconds of reading from an hour of lunch, and lunch is the
              // common case here: gated calls arrive while the reader is
              // somewhere else entirely.
              hidden_ms: Math.round(Math.max(0, hiddenTotal() - hiddenWhenShown)),
              expanded_details: expandedDetails,
              review_id: approval.id,
            })
          }
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
    [container, deciding, log],
  )

  return { approvals, deciding, decide }
}
