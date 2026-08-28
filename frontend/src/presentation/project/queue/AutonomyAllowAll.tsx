import { useAutonomy } from '@application/autonomy/use-autonomy.ts'
import { levelOf } from '@domain/autonomy/autonomy.ts'
import type { SessionId } from '@domain/shared/identifier.ts'

import { Button } from '../../common/primitives.tsx'
import { INSTANCE_WIDE, NO_POLICY } from './autonomy-copy.ts'

/** "Stop asking me", where the asking happens.
 *
 * This lives in the worker drawer, immediately under `Approvals`, because that
 * is where the pain is: somebody answering the same approval for the fifth
 * time should not have to navigate to a settings page to make it stop. The
 * full per-tool panel in the project page's queue header reads and writes the
 * same state through `useAutonomy`, so the two can never show different levels.
 *
 * **One button, and there used to be two.** The second one also autoed the
 * stage review gate, which allow-all deliberately held back -- the gate was the
 * one place a person was guaranteed to be looking before a run built on what it
 * had produced. The workflow system is gone and so is that gate, so there is no
 * subset left to hold back and nothing for a second button to select. What that
 * costs is stated rather than left to be found: nothing in this build now
 * reserves a tool from allow-all, so "allow everything" means everything.
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
 * **`.autonomy-warn` and `.autonomy-error` are gone from this file too**, and
 * the argument that kept them is the one that turned out to be wrong. It ran:
 * they are shared with `AutonomyPanel`, a real course-page surface, so
 * converting them would be the forbidden port. Sharing is not what makes a port
 * forbidden — dying with the wrong screen is. This control outlives
 * `course.css` and `AutonomyPanel` does not, so the rules stay there for the
 * panel and the two elements here carry the same declarations as utilities.
 * The cost is one duplicated look for as long as both exist, which ends the day
 * `course.css` is deleted; the alternative was the decision bar's scope warning
 * losing its 2px accent rule silently, and that warning is the one thing this
 * panel is shaped to make unskippable.
 *
 * **`.sub` is gone as well, for the opposite reason: it was already dead.** Its
 * only definition anywhere under `src/styles/` was `tree.css`'s `.view-head
 * .sub`, which needed an ancestor the decision bar has never provided — so the
 * dimmed secondary text this file has been asking for since it moved has been
 * rendering at full `--fg` all along. **That definition is itself deleted as of
 * 2026-08-14**, with the rest of the `.view-head` family, once the course and
 * research views took its last live users with them: `.sub` now has no
 * definition anywhere at all. Which is the same conclusion arrived at twice —
 * the class was decorative in name only, and this paragraph was written when
 * the rule still existed and could still have been mistaken for live.
 * The dressing was plainly meant to apply
 * (every `.sub` here is a subordinate line beside a `<strong>` or under a
 * heading), so it is `text-fg-dim` now rather than deleted, on the three
 * elements where the intent is unambiguous. `.view-head .sub`'s `font-size` and
 * `margin-top` are deliberately *not* carried: those are the landing view's
 * heading rhythm, and this control is not a view head.
 *
 * The one exception is the scope warning, which drops `.sub` outright: it also
 * carries `.autonomy-warn`, whose whole point is `color: var(--fg)` — the
 * warning is the loudest line in the panel, not a subordinate one.
 *
 * **This used to say `m-[0px]`, and the reason is worth keeping.** Tailwind
 * builds a bare step it has no explicit key for as `calc(var(--spacing) * N)`
 * off the base `--spacing` variable, which `theme.css` deliberately omits — so
 * `m-0` generated no rule at all and this paragraph kept the user agent's 1em
 * margin, which is exactly what the `margin: 0` it replaced existed to remove.
 * The arbitrary value was the local dodge. `theme.css` now declares
 * `--spacing-0`, so `m-0` emits `margin:var(--spacing-0)` and the two
 * spellings are equivalent; this reads as the ordinary one because there is no
 * longer anything to dodge. If `--spacing-0` is ever removed, `check-tailwind.mjs`
 * fails rather than this paragraph silently regaining its margin.
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
    // was. `sub` used to stay here on the grounds that it was not one of the
    // classes this file took over; it turned out to name no rule at all from
    // this position, so it is `text-fg-dim` — the dimming it was asking for.
    return (
      <p className="m-0 border-l border-line-soft pl-3 text-fg-dim">
        {readNotFound || !readError ? NO_POLICY : readError}
      </p>
    )
  }

  const gatedNotAuto = policy.gated.filter((tool) => levelOf(policy, tool) !== 'auto')

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
        <span className="text-fg-dim">
          {gatedNotAuto.length > 0
            ? `${gatedNotAuto.length} tool(s) still wait for a person.`
            : 'Every gated tool already runs without asking.'}
        </span>
      </div>

      <p className="m-0 rounded-r-md border-l-2 border-accent bg-bg-panel-2 px-[8px] py-2 text-fg">
        {INSTANCE_WIDE}
      </p>

      <div className="flex flex-wrap gap-2">
        <Button
          tone="accent"
          small
          disabled={!canWrite || writing || gatedNotAuto.length === 0}
          onClick={() => allowAll()}
        >
          {writing ? 'Changing…' : 'Allow everything'}
        </Button>
      </div>

      {lastAllowAll ? (
        <p className="m-0 text-fg-dim" role="status">
          {lastAllowAll.changed.size === 0
            ? 'Nothing moved — those tools were already set that way.'
            : `Changed ${lastAllowAll.changed.size} tool(s): ${[...lastAllowAll.changed.keys()].join(', ')}.`}
        </p>
      ) : null}

      {writeError ? (
        <p
          className="m-0 rounded-r-md border-l-2 border-k-failure bg-del-bg px-[8px] py-2 font-mono text-xs text-del-fg"
          role="alert"
        >
          {writeError}
        </p>
      ) : null}
    </section>
  )
}
