import { useAutonomy } from '@application/autonomy/use-autonomy.ts'
import {
  levelMeaning,
  levelOf,
  levelsToOffer,
  levelTally,
  type AutonomyPolicyView,
} from '@domain/autonomy/autonomy.ts'
import type { SessionId } from '@domain/shared/identifier.ts'

import { Chip } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
import { INSTANCE_WIDE, NO_POLICY, NO_SESSION } from './autonomy-copy.ts'

/** Every gated tool, and what the agent may do with it without asking.
 *
 * Reached from the lock in the chrome (`AutonomyLock`) rather than from a band
 * of the project page's queue header, and the move is the reason this file is
 * under `shell/` now. The policy is instance-wide: it is not a property of the
 * project you happen to have open, which is the same test `Shell.tsx` applies
 * to everything else in that bar. On the project page it was also a band a
 * reader scrolled past on the way to the queue, in the region whose stated job
 * is what you *act* on rather than what the run is configured with.
 *
 * The other surface over this policy is `AutonomyAllowAll`, in the shell's
 * decision bar: this is the reading surface, that is for the person mid-approval
 * who wants it to stop. Both go through `useAutonomy`, one query key, so a write
 * on either is reflected on the other -- they are not two copies of this state,
 * they are two renders of one.
 *
 * **The rows come from `gated`, never from a list in this file.** The server
 * sends its own `GATED_TOOLS` precisely so this cannot drift; a hardcoded list
 * would go stale as a *missing switch*, which is a tool nobody can manage from
 * the web and nothing on screen to say so.
 *
 * **The scope warning is not polish.** One policy object serves every session
 * in the process, so a switch flipped from any page changes what the agent may
 * do in every session on the instance -- while the audit record lands only on
 * the session this page is attached to. That asymmetry is invisible from the
 * control, so it is written above the controls where it cannot be missed. See
 * `INSTANCE_WIDE`.
 *
 * **No row is marked any more, and that is a subtraction rather than a
 * simplification.** `advance_stage` used to carry a "review gate" chip and a
 * sentence saying "allow everything" would leave it alone. The workflow system
 * is gone, so no tool is held back from allow-all and there is nothing to mark.
 *
 * **The `<details>` fold is gone, and it did not become a `Disclosure`.** The
 * fold existed for one reason -- open, eight tools by three levels filled the
 * first screen of the page this was a band of -- and a dialog opened
 * deliberately from a lock has no page to push down. What it costs is the
 * find-in-page argument that kept it out of the controlled-state migration: a
 * reader can no longer type a tool's name into find-in-page from the project
 * page and have the panel open to it, because the panel is not on that page at
 * all. Nothing is folded here now, so there is nothing to reach past.
 *
 * **Dressed in utilities, because it outlives `course.css`.** Every
 * `.autonomy-*` rule this file used to write lived in a stylesheet on the
 * die-with-its-screen list, which was correct while this was a course-page
 * band and became a deletion trap the moment it moved into the chrome: the
 * whole panel would have lost its layout on the day the course view is
 * rebuilt, silently -- jsdom applies no stylesheet and a class that resolves to
 * nothing raises no error. The rules are deleted from `course.css` in the same
 * commit rather than left dead. Arbitrary values are the deleted rules' own
 * (`gap-[8px]`, `py-[4px]`, `basis-[12ch]`): 8, 4 and 12ch are not on this
 * project's spacing scale, and rounding them would be a visual change smuggled
 * into a filing fix.
 *
 * Radio inputs, not a custom widget: a fieldset of radios gives arrow-key
 * traversal, a group label a screen reader announces, and a selected state
 * that survives without any of it being reimplemented here.
 */
export const AutonomyPanel = ({ sessionId }: { sessionId: SessionId | null }) => {
  const { policy, loading, readError, readNotFound, canWrite, setLevel, writing, writeError } =
    useAutonomy(sessionId)

  if (loading) return <p className="m-0 text-fg-dim">reading the policy…</p>

  // Not an empty set of switches. An empty panel implies "nothing is gated",
  // which is the opposite of what an unreadable policy means.
  if (!policy)
    return <p className="m-0 text-fg-dim">{readNotFound || !readError ? NO_POLICY : readError}</p>

  return (
    <div className="flex flex-col gap-3">
      {/* The tally the fold's summary used to carry. It is no longer standing in
          for hidden content -- the rows are right below it -- but "six ask, two
          auto" is the one fact a reader wants before reading eight rows, and it
          is the sentence they would otherwise assemble by counting. */}
      <div className="flex flex-wrap items-center gap-[8px]">
        <span className="flex flex-wrap gap-1">
          {levelTally(policy).map(([level, count]) => (
            <Chip key={level}>
              {count} {level}
            </Chip>
          ))}
        </span>
      </div>

      <p className="m-0 rounded-r-md border-l-2 border-accent bg-bg-panel-2 px-[8px] py-2 text-fg">
        {INSTANCE_WIDE}
      </p>
      {!canWrite ? <p className="m-0 text-fg-dim">{NO_SESSION}</p> : null}

      {writeError ? (
        // The server's message, verbatim: it names the value it rejected
        // (`unknown autonomy level: 'sometimes'`), and no sentence written
        // here could reconstruct that.
        <p
          className="m-0 rounded-r-md border-l-2 border-k-failure bg-del-bg px-[8px] py-2 font-mono text-xs text-del-fg"
          role="alert"
        >
          {writeError}
        </p>
      ) : null}

      <ul className="m-0 flex list-none flex-col gap-2 p-0">
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
    </div>
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

  return (
    <li className="flex flex-wrap items-baseline gap-3 border-0 border-t border-solid border-line-soft py-[4px]">
      {/* `border-0` beside the directional `border-t`, which is both halves of
          one fix rather than belt and braces: `border-solid` is the shorthand,
          so without the zero the three sides that get a style and no width fall
          back to the browser's `medium` and the row draws a box. */}
      <fieldset
        className="m-0 flex flex-wrap items-baseline gap-3 border-0 p-0"
        disabled={disabled}
      >
        <legend className="flex items-center gap-2 p-0">
          <span className="font-mono text-sm">{tool}</span>
        </legend>

        <div className="flex items-center gap-3">
          {levelsToOffer(current).map((level) => (
            <label
              key={level}
              className={
                disabled
                  ? 'flex cursor-default items-center gap-1 text-xs text-fg-faint'
                  : 'flex cursor-pointer items-center gap-1 text-xs text-fg-dim'
              }
            >
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

      <span className="m-0 flex-auto basis-[12ch] text-fg-dim">
        {current === null
          ? // The server named this tool as gated and gave it no level. Saying
            // "ask" here would be inventing a safety claim nobody made.
            'This build was not told what level this tool is at.'
          : levelMeaning(current)}
      </span>
    </li>
  )
}
