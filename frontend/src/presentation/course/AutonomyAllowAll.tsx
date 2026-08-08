import { useAutonomy } from '@application/autonomy/use-autonomy.ts'
import { levelOf, stageGatesStillAsking } from '@domain/autonomy/autonomy.ts'
import type { SessionId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'
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
    return <p className="sub autonomy-off">{readNotFound || !readError ? NO_POLICY : readError}</p>
  }

  const held = stageGatesStillAsking(policy)
  const gatedNotAuto = policy.gated.filter(
    (tool) => !policy.stageGates.includes(tool) && levelOf(policy, tool) !== 'auto',
  )

  return (
    <section className="autonomy-allow" aria-label="Stop being asked">
      <div className="autonomy-allow-head">
        <strong>Stop being asked</strong>
        <span className="sub">
          {gatedNotAuto.length > 0
            ? `${gatedNotAuto.length} tool(s) still wait for a person.`
            : 'Every tool outside the review gate already runs without asking.'}
        </span>
      </div>

      <p className="sub autonomy-warn">{INSTANCE_WIDE}</p>

      <div className="autonomy-allow-actions">
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
        <Button
          tone="quiet"
          small
          disabled={!canWrite || writing || held.length === 0}
          onClick={() => allowAll(true)}
          title="Also autos the workflow review gate, so a run can cross stage boundaries unattended"
        >
          Also allow the review gate
        </Button>
      </div>

      {lastAllowAll ? (
        <p className="sub autonomy-result" role="status">
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
