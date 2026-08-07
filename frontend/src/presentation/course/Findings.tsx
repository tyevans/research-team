import { severityLabel, type Course } from '@domain/project/course.ts'

import { Chip } from '../common/primitives.tsx'

/** What the *current* stage's own checks say, right now.
 *
 * Only the current stage's: a stage that has been left has a findings artifact
 * recorded at the moment it was left, and that record is what its gate decision
 * was made against. Recomputing it against a course that has since grown would
 * show a different table and quietly present it as the one the reviewer saw. */
export const Findings = ({ course }: { course: Course }) => {
  if (course.findings.length === 0 && course.unimplementedChecks.length === 0) return null

  return (
    <>
      <h3 className="findings-head">This stage’s checks</h3>
      <ul className="findings">
        {course.findings.map((finding, index) => (
          <li key={index} className={`finding finding-${finding.severity}`}>
            <Chip tone={finding.severity}>{severityLabel(finding.severity)}</Chip>
            <span className="finding-check">{finding.check}</span>
            <span className="finding-msg">{finding.message}</span>
            {finding.suggestedEdit ? (
              <span className="finding-fix">→ {finding.suggestedEdit}</span>
            ) : null}
          </li>
        ))}
        {course.unimplementedChecks.length > 0 ? (
          // A declared check that never runs is a guarantee the preset claims
          // and nothing provides. Silence about it is worse than declaring none.
          <li className="finding finding-unimplemented">
            <Chip>not run</Chip>
            <span className="finding-msg">
              This stage declares {course.unimplementedChecks.length} check
              {course.unimplementedChecks.length === 1 ? '' : 's'} that nothing implements:{' '}
              {course.unimplementedChecks.join(', ')}. Nothing they would have found is known.
            </span>
          </li>
        ) : null}
      </ul>
    </>
  )
}
