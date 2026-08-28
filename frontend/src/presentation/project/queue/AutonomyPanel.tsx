import { useAutonomy } from '@application/autonomy/use-autonomy.ts'
import {
  isStageGate,
  levelMeaning,
  levelOf,
  levelsToOffer,
  levelTally,
  type AutonomyPolicyView,
} from '@domain/autonomy/autonomy.ts'
import type { SessionId } from '@domain/shared/identifier.ts'

import { Chip } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
import { INSTANCE_WIDE, NO_POLICY, NO_SESSION, STAGE_GATE_HELD } from './autonomy-copy.ts'

/** Every gated tool, and what the agent may do with it without asking.
 *
 * On the course page rather than in the drawer because eight tools by three
 * levels needs room, and because this is the reading surface: the drawer's
 * `AutonomyAllowAll` is for the person mid-approval who wants it to stop.
 * Both go through `useAutonomy`, one query key, so a write on either is
 * reflected on the other — they are not two copies of this state, they are two
 * renders of one.
 *
 * **The rows come from `gated`, never from a list in this file.** The server
 * sends its own `GATED_TOOLS` precisely so this cannot drift; a hardcoded list
 * would go stale as a *missing switch*, which is a tool nobody can manage from
 * the web and nothing on screen to say so.
 *
 * **The scope warning is not polish.** One policy object serves every session
 * in the process, so a switch flipped on this project's page changes what the
 * agent may do in every session on the instance — while the audit record lands
 * only on the session this page is attached to. That asymmetry is invisible
 * from the control, so it is written above the controls where it cannot be
 * missed. See `INSTANCE_WIDE`.
 *
 * **A stage gate is marked and explained rather than hidden.** `advance_stage`
 * can be set to `auto` here, one deliberate click at a time — what it is not is
 * swept along by "allow everything". The row says why its floor exists, so the
 * reader choosing to lift it knows what they are removing.
 *
 * Radio inputs, not a custom widget: a fieldset of radios gives arrow-key
 * traversal, a group label a screen reader announces, and a selected state
 * that survives without any of it being reimplemented here.
 */
export const AutonomyPanel = ({ sessionId }: { sessionId: SessionId | null }) => {
  const { policy, loading, readError, readNotFound, canWrite, setLevel, writing, writeError } =
    useAutonomy(sessionId)

  return (
    // Closed until asked for. This policy is instance-wide and changes rarely,
    // and open it filled the first screen of the course page -- so a reader
    // arriving to see how the run was going met eight tools by three radio
    // levels before a single stage or artifact. The summary keeps the fact
    // worth knowing at a glance (how many tools run without asking) on the
    // page, and the twenty-four controls behind one click.
    //
    // `<details>` rather than a state hook: it gives the disclosure keyboard
    // behaviour, the expanded/collapsed state a screen reader announces, and
    // find-in-page that opens the panel to reach a match -- none of which
    // would survive being reimplemented here.
    //
    // **This is the one fold in the console that is deliberately not a
    // `Disclosure`, and phase 2 left it alone on purpose.** The spec (§9)
    // takes the controlled arm everywhere and records losing find-in-page as
    // "a real, small, permanent loss"; it is neither small nor worth it here.
    // The argument for controlled state is S-F48 -- open state surviving a
    // refetch -- and this panel has no refetch to survive: the policy is
    // instance-wide and changes when somebody changes it. What it does have is
    // eight tools by three levels behind one summary, which is precisely the
    // content a reader finds by typing a tool's name into find-in-page. Paying
    // a real loss for a benefit that does not apply is not consistency, it is
    // tidiness. `scripts/check-deleted.mjs` scopes its no-`<details>` rule to
    // `presentation/session` for this reason.
    <details className="autonomy-disclosure">
      <summary className="autonomy-head">
        <h3 className="autonomy-title">What the agent may do without asking</h3>
        {policy ? (
          <span className="autonomy-tally">
            {levelTally(policy).map(([level, count]) => (
              <Chip key={level}>
                {count} {level}
              </Chip>
            ))}
          </span>
        ) : null}
      </summary>

      {loading ? (
        <p className="sub autonomy-sub">reading the policy…</p>
      ) : !policy ? (
        // Not an empty set of switches. An empty panel implies "nothing is
        // gated", which is the opposite of what an unreadable policy means.
        <p className="sub autonomy-sub">{readNotFound || !readError ? NO_POLICY : readError}</p>
      ) : (
        <>
          <p className="sub autonomy-warn">{INSTANCE_WIDE}</p>
          {!canWrite ? <p className="sub autonomy-sub">{NO_SESSION}</p> : null}

          {writeError ? (
            // The server's message, verbatim: it names the value it rejected
            // (`unknown autonomy level: 'sometimes'`), and no sentence written
            // here could reconstruct that.
            <p className="autonomy-error" role="alert">
              {writeError}
            </p>
          ) : null}

          <ul className="autonomy-list">
            {policy.gated.map((tool) => (
              <ToolRow
                key={tool}
                tool={tool}
                policy={policy}
                disabled={!canWrite || writing}
                onChoose={(level) => setLevel(tool, level)}
              />
            ))}
          </ul>
        </>
      )}
    </details>
  )
}

const ToolRow = ({
  tool,
  policy,
  disabled,
  onChoose,
}: {
  tool: string
  policy: AutonomyPolicyView
  disabled: boolean
  onChoose: (level: string) => void
}) => {
  const current = levelOf(policy, tool)
  const gate = isStageGate(policy, tool)

  return (
    <li className={gate ? 'autonomy-row autonomy-row-gate' : 'autonomy-row'}>
      <fieldset className="autonomy-field" disabled={disabled}>
        <legend className="autonomy-tool">
          <span className="autonomy-tool-name">{tool}</span>
          {gate ? (
            <Tooltip
              explanation={`“Allow everything” leaves this alone — it is ${STAGE_GATE_HELD}`}
            >
              <Chip tone="readonly">review gate</Chip>
            </Tooltip>
          ) : null}
        </legend>

        <div className="autonomy-levels">
          {levelsToOffer(current).map((level) => (
            <label key={level} className="autonomy-level">
              {/* The trigger is the radio rather than the label around it. The
                  label is what a mouse hovered before, and it is wider, but it
                  is not focusable and Tooltip's own wrapper is a `<button>` —
                  wrapping a label that contains a radio in a button nests one
                  interactive element inside another, which is the arrangement
                  `aria` has no reading for. A radio passes a ref and is
                  already a tab stop, so `asChild` costs one element and gains
                  the keyboard. */}
              <Tooltip asChild explanation={levelMeaning(level)}>
                <input
                  type="radio"
                  name={`autonomy-${tool}`}
                  value={level}
                  checked={current === level}
                  disabled={disabled}
                  onChange={() => onChoose(level)}
                />
              </Tooltip>
              <span>{level}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <span className="sub autonomy-meaning">
        {current === null
          ? // The server named this tool as gated and gave it no level. Saying
            // "ask" here would be inventing a safety claim nobody made.
            'This build was not told what level this tool is at.'
          : levelMeaning(current)}
        {gate ? ` — ${STAGE_GATE_HELD}` : ''}
      </span>
    </li>
  )
}
