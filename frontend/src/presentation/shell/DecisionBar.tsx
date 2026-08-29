import { AutonomyAllowAll } from '../project/topics/AutonomyAllowAll.tsx'
import { Approvals } from '../session/Approvals.tsx'
import { useApprovalFeed } from './use-approval-feed.ts'

/** The one place in the console where a gated call is answered.
 *
 * **What this replaces:** three call sites rendering `Approvals` — the session
 * view's conversation footer, the worker drawer, and the course page through
 * that drawer — each of which could only show the approvals belonging to the
 * session it was already looking at. So the console's answer to "is anything
 * waiting on me?" was "depends where you are standing", and the honest way to
 * find out was to open every session in turn. An approval blocks an agent
 * until a person answers it; a person cannot answer what they cannot see.
 *
 * **Why it is in the flow and not floating.** It could have been an
 * `OverlayHost` layer, and that was the first shape. The problem is Escape: a
 * layer that is mounted for as long as something is pending is the *topmost*
 * layer, and the host gives Escape to exactly one layer — so a bar that is
 * always up either swallows Escape from every drawer beneath it or takes it
 * and does nothing with it. Neither is worth a floating bar. In the surface it
 * needs no stacking order, no layer, and no key, and the only thing it costs
 * is that the route below is shorter while a decision is pending — which is
 * the correct emphasis anyway.
 *
 * Renders nothing at all when nothing is pending, so every page is exactly
 * what it was until an agent asks for something.
 */
export const DecisionBar = () => {
  const { approvals, deciding, decide } = useApprovalFeed()

  const pending = [...approvals.values()]
  if (pending.length === 0) return null

  // One `AutonomyAllowAll` for the bar, addressed at the oldest pending
  // approval's session. The policy it writes is instance-wide — the control
  // says so on itself, which is why it is safe to render once here rather than
  // per card — so the session it is handed only decides which session's
  // `useAutonomy` query backs it, not what the button does. Per card would be
  // N identical panels making one instance-wide change.
  const oldest = pending[0]

  return (
    <section
      className="flex max-h-[45%] shrink-0 flex-col gap-3 overflow-y-auto border-b border-k-tool bg-bg-panel p-3"
      aria-label="Decisions waiting"
    >
      <header className="flex flex-wrap items-baseline gap-2">
        <strong className="text-lg">
          {pending.length === 1
            ? 'A call is waiting on you'
            : `${pending.length} calls are waiting`}
        </strong>
        {/* Said out loud because the bar is the same on every route and a
            reader who did not open the session it belongs to has no other way
            to know which agent stopped. */}
        <span className="text-sm text-fg-dim">
          from {new Set(pending.map((approval) => approval.sessionId)).size} session(s)
        </span>
      </header>

      <Approvals approvals={approvals} deciding={deciding} onDecide={decide} />

      {/* Directly under the approvals, because this is the control that
          answers "I wish I could stop being asked" — and asking somebody to
          navigate to a settings surface in order to say that is how the
          REPL's `/autonomy` came to be the only way to do it. The scope
          warning it renders is load-bearing: the policy is instance-wide even
          though it is reached through one session. */}
      {oldest ? <AutonomyAllowAll sessionId={oldest.sessionId} /> : null}
    </section>
  )
}
