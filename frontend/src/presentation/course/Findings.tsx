import clsx from 'clsx'

import { severityLabel, type Course } from '@domain/project/course.ts'

import { SEVERITY_DRESS, unimplementedChecksWarning } from '../common/findings-copy.ts'
import { Chip } from '../common/primitives.tsx'

/** A finding row's left edge, which is the whole of its severity dressing.
 *
 * These were `.finding-invariant` and its four siblings in `course.css`. The
 * split between this map and `ROW` below is the same one `Chip`'s `dress` prop
 * documents and is here for the same reason: `border-l-line` in the base string
 * and `border-l-k-failure` in the override are both `@layer utilities`, and
 * which one wins is Tailwind's sort order rather than the class attribute's. So
 * `ROW` names no left colour at all and this map is the only writer of one.
 *
 * A severity the map has never seen — the reviewer prompts author the string —
 * falls back to `--color-line`, which is exactly what an unmatched
 * `finding-${severity}` class already produced. `unimplemented` is not a
 * severity and takes the same fallback deliberately: it is a gap in the preset,
 * not a verdict about the work.
 */
const SEVERITY_EDGE: Record<string, string> = {
  // An invariant fails invisibly -- there is nothing for a human to look at and
  // no judgement to make -- so it is the one that gets the loud edge.
  invariant: 'border-l-k-failure',
  blocking: 'border-l-accent',
  advisory: 'border-l-line',
  // Not defects, and edged so they cannot be mistaken for any: these mark work
  // no run can clear by itself, waiting on a person or on a critic pass.
  human_gate: 'border-l-k-session',
  critic_gate: 'border-l-k-compaction',
}

/** `border-0` first, then the one edge. Without the `border-0` the
 *  `border-solid` gives the other three sides a style with no width, and the
 *  browser's `medium` (~3px) fills it in -- a rule meant for a left edge draws
 *  a box. `CLAUDE.md` records this having shipped in both directions. */
const ROW =
  'flex flex-wrap items-baseline gap-[8px] border-0 border-l-2 border-solid bg-bg-panel-2 px-[8px] py-[5px] text-sm'

/** What the *current* stage's own checks say, right now.
 *
 * Only the current stage's: a stage that has been left has a findings artifact
 * recorded at the moment it was left, and that record is what its gate decision
 * was made against. Recomputing it against a course that has since grown would
 * show a different table and quietly present it as the one the reviewer saw.
 *
 * **`open` is the route's `finding` id, and it was not reaching here.**
 * `#/p/<id>/finding/<check>` has parsed and opened this tab since slice 0 with
 * the id dropped, so a link to one finding produced an unmarked list of all of
 * them. Matched on `finding.check`: a `Finding` has no id of its own, and the
 * check name is the only stable thing about a row -- the array index is not,
 * because the list is recomputed against a course that grows.
 *
 * The cost of matching on `check`, said rather than hidden: two findings from
 * one check both mark. That is the honest answer for a link that names a check,
 * and it beats marking the wrong single row.
 */
export const Findings = ({ course, open = null }: { course: Course; open?: string | null }) => {
  if (course.findings.length === 0 && course.unimplementedChecks.length === 0) return null

  return (
    <>
      <h3 className="font-medium m-0 mb-[4px] text-sm text-fg-dim">This stage’s checks</h3>
      <ul className="m-0 flex list-none flex-col gap-[4px] p-0">
        {course.findings.map((finding, index) => (
          // Two maps for one string, on purpose: `SEVERITY_DRESS` is shared
          // with `GateReview` because a chip looks the same wherever it is
          // rendered, and `SEVERITY_EDGE` is local because only this list has
          // rows to edge. Merging them would put a left-border utility on the
          // gate review's chips, where there is no row for it to draw on.
          <li
            key={index}
            className={clsx(
              ROW,
              SEVERITY_EDGE[finding.severity] ?? 'border-l-line',
              finding.check === open && 'bg-bg-raise',
            )}
            data-severity={finding.severity}
            aria-current={finding.check === open ? 'true' : undefined}
          >
            {/* `dress` rather than `tone`: `chip-${severity}` has resolved to
                nothing since those five rules left `course.css`. */}
            <Chip dress={SEVERITY_DRESS[finding.severity]}>{severityLabel(finding.severity)}</Chip>
            <span className="font-mono text-xs text-fg-dim">{finding.check}</span>
            <span className="grow basis-[340px]">{finding.message}</span>
            {finding.suggestedEdit ? (
              <span className="text-fg-dim">→ {finding.suggestedEdit}</span>
            ) : null}
          </li>
        ))}
        {course.unimplementedChecks.length > 0 ? (
          // A declared check that never runs is a guarantee the preset claims
          // and nothing provides. Silence about it is worse than declaring none.
          <li className={clsx(ROW, 'border-l-line')} data-severity="unimplemented">
            <Chip>not run</Chip>
            <span className="grow basis-[340px]">
              {unimplementedChecksWarning(course.unimplementedChecks)}
            </span>
          </li>
        ) : null}
      </ul>
    </>
  )
}
