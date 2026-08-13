import { useAutonomy } from '@application/autonomy/use-autonomy.ts'
import { levelOf, stageGatesStillAsking } from '@domain/autonomy/autonomy.ts'
import type { SessionId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
import { INSTANCE_WIDE, NO_POLICY, STAGE_GATE_HELD } from './autonomy-copy.ts'

/** "Stop asking me", where the asking happens.
 *
 * This lives in the worker drawer, immediately under `Approvals`, because that
 * is where the pain is: somebody answering the same approval for the fifth
 * time should not have to navigate to a settings page to make it stop. The
 * full per-tool panel on the course page reads and writes the same state
 * through `useAutonomy`, so the two can never show different levels.
 *
 * **Two buttons, not one with a checkbox.** Allow-all deliberately leaves the
 * stage gates asking, and the second button is the only way to include them.
 * Splitting them makes auto-ing the review gate possible but never accidental
 * — a checkbox left ticked from a previous visit is exactly the accident that
 * matters here. After a default allow-all the panel says what stayed put and
 * why, rather than appearing to have half-failed.
 *
 * The scope warning is rendered on the control, not in a tooltip: see
 * `INSTANCE_WIDE`.
 *
 * **Styled with Tailwind utilities, and this one is not tidying.** The layout
 * rules lived in `course.css` under a heading naming the decision bar, which
 * was already conceded there as the wrong file. That filing became a trap
 * when this control moved into the shell's decision bar: `course.css` is on
 * the die-with-its-screen list, so deleting it when the course view is rebuilt
 * would silently unstyle a control that is still on screen — no test failure,
 * no error, the same failure family as the combinator hazard the spec records
 * for this policy. Utilities travel with the markup, so the trap is gone
 * rather than deferred. This is not a licence to port the other stylesheets:
 * the standing policy is that they are deleted, never ported.
 *
 * **Still shared, and still a smaller version of the same trap:**
 * `.autonomy-warn` and `.autonomy-error` below are `course.css` rules that
 * `AutonomyPanel` — a genuine course-page surface — also uses. They are left
 * alone deliberately, because converting them would be the forbidden port.
 * `course.css` says the same thing at the rules themselves.
 *
 * **`m-[0px]` rather than `m-0`, and this is not a style choice.** Tailwind
 * builds `m-0` as `calc(var(--spacing) * 0)`, and `--spacing` — the base step
 * the whole scale is derived from — is deliberately absent from `theme.css`,
 * which declares `--spacing-1` … `--spacing-6` and no root. So `m-0` generates
 * no rule at all and the paragraph keeps the user agent's 1em margin, which is
 * exactly what the deleted `margin: 0` existed to remove. Measured: grepping
 * the built stylesheet for `.m-0` after a `vite build` returns nothing, while
 * `.m-\[0px\]` is emitted as `margin:0`. `Approvals.tsx` and `GateReview.tsx`
 * both write `m-0` and `p-0` today and are silently getting nothing; that is a
 * pre-existing defect on already-shipped surfaces rather than one this change
 * introduces, and it is not fixed here because doing so moves pixels on two
 * surfaces this commit is not about.
 */
export const AutonomyAllowAll = ({ sessionId }: { sessionId: SessionId }) => {
  const {
    policy,
    loading,
    readError,
    readNotFound,
    canWrite,
    allowAll,
    writing,
    writeError,
    lastAllowAll,
  } = useAutonomy(sessionId)

  if (loading) return null
  if (readError || !policy) {
    // Quiet rather than alarming: an unwired policy is a fact about the build,
    // and this control is a convenience beside the approvals rather than the
    // reason the drawer is open. Said, though, not hidden — a missing control
    // with no explanation reads as a console that lost a feature.
    // Same indent-behind-a-rule as the section below, because it stands in the
    // same place: the reason the control is absent belongs where the control
    // was. `sub` stays — it is not one of the classes this file took over.
    return (
      <p className="sub m-[0px] border-l border-line-soft pl-3">
        {readNotFound || !readError ? NO_POLICY : readError}
      </p>
    )
  }

  const held = stageGatesStillAsking(policy)
  const gatedNotAuto = policy.gated.filter(
    (tool) => !policy.stageGates.includes(tool) && levelOf(policy, tool) !== 'auto',
  )

  return (
    // The indent behind a rule is `.extraction`'s language, borrowed on the
    // same argument: this control belongs to the approvals above it rather
    // than standing on its own. `gap-2` is 6px and `pl-3` is 10px — the
    // `--spacing-*` steps the deleted rules already spelled out by hand.
    <section
      className="flex flex-col gap-2 border-l border-line-soft pl-3"
      aria-label="Stop being asked"
    >
      {/* `gap-[8px]` is arbitrary because 8px is not on the spacing scale
          (3/6/10/14); the deleted rule used the literal too. Rounding it to
          `gap-2` or `gap-3` would move the head's baseline row by 2px for
          tidiness, which is a visual change smuggled into a filing fix. */}
      <div className="flex flex-wrap items-baseline gap-[8px] text-sm">
        <strong>Stop being asked</strong>
        <span className="sub">
          {gatedNotAuto.length > 0
            ? `${gatedNotAuto.length} tool(s) still wait for a person.`
            : 'Every tool outside the review gate already runs without asking.'}
        </span>
      </div>

      <p className="sub autonomy-warn">{INSTANCE_WIDE}</p>

      <div className="flex flex-wrap gap-2">
        <Button
          tone="accent"
          small
          disabled={!canWrite || writing || gatedNotAuto.length === 0}
          onClick={() => allowAll(false)}
        >
          {writing ? 'Changing…' : 'Allow everything except the review gate'}
        </Button>
        {/* Deliberately separate, deliberately not the primary tone: this one
            removes the last place a person is guaranteed to be looking. */}
        <Tooltip
          asChild
          explanation="Also autos the workflow review gate, so a run can cross stage boundaries unattended"
        >
          <Button
            tone="quiet"
            small
            disabled={!canWrite || writing || held.length === 0}
            onClick={() => allowAll(true)}
          >
            Also allow the review gate
          </Button>
        </Tooltip>
      </div>

      {lastAllowAll ? (
        <p className="sub m-[0px]" role="status">
          {lastAllowAll.changed.size === 0
            ? 'Nothing moved — those tools were already set that way.'
            : `Changed ${lastAllowAll.changed.size} tool(s): ${[...lastAllowAll.changed.keys()].join(', ')}.`}
          {held.length > 0 ? (
            <>
              {' '}
              <strong>{held.join(', ')}</strong> {STAGE_GATE_HELD}
            </>
          ) : null}
        </p>
      ) : null}

      {writeError ? (
        <p className="autonomy-error" role="alert">
          {writeError}
        </p>
      ) : null}
    </section>
  )
}
