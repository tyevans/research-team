import { writtenCount, type Course, type StageProgress } from '@domain/project/course.ts'

import { Chip } from '../common/primitives.tsx'
import { Artifact, CourseFileLink } from './Artifacts.tsx'

/** One row of the rail, and its detail when opened.
 *
 * Every stage of the preset is a row whether or not it has run -- a rail built
 * from what happened can only show what happened, and the question it answers
 * is what was supposed to. */
export const Stage = ({
  stage,
  course,
  open,
  onToggle,
}: {
  stage: StageProgress
  course: Course
  open: boolean
  onToggle: () => void
}) => {
  const written = writtenCount(stage.outputs)

  return (
    <li className={`rail-item rail-item-${stage.status}`}>
      <button type="button" className="rail-row" aria-expanded={open} onClick={onToggle}>
        <span className={`rail-dot rail-${stage.status}`} aria-hidden="true" />
        <span className="rail-index">{stage.index}</span>
        <span className="rail-name">{stage.name}</span>
        {/* Written-of-declared, not a percentage: a stage owing two artifacts
            with one written is a specific situation, and "50%" is not. */}
        {stage.outputs.length > 0 ? (
          <span
            className={`rail-count${written < stage.outputs.length ? ' rail-short' : ''}`}
            title={`${written} of ${stage.outputs.length} declared artifacts written`}
          >
            {written}/{stage.outputs.length}
          </span>
        ) : (
          <span className="rail-count empty" title="This stage declares no artifact of its own.">
            —
          </span>
        )}
        <Chip tone={stage.status}>{stage.status}</Chip>
      </button>

      {open ? (
        <div className="rail-detail">
          <div className="rail-meta-row">
            <span className="muted">{stage.id}</span>
            <span className="muted">spine {stage.spine}</span>
            <span className="muted">{stage.scopeLevel}</span>
            <span className="muted">{stage.kind}</span>
          </div>
          {stage.gateDecisions.length > 0 ? (
            // What a human is allowed to answer here. `halt` is the one worth
            // seeing in advance: the pipeline is structurally biased toward
            // producing its own output, and the gates that can stop it are the
            // counterweight.
            <div className="rail-gate">
              <span className="muted">
                gate{stage.reviewerRole ? ` (${stage.reviewerRole})` : ''}:{' '}
              </span>
              <span>{stage.gateDecisions.join(' · ')}</span>
            </div>
          ) : null}
          {stage.findingsReport ? (
            <div className="rail-report">
              <span className="muted">report: </span>
              <CourseFileLink course={course} path={stage.findingsReport} />
            </div>
          ) : null}
          {stage.outputs.length === 0 ? (
            <p className="muted">
              Produces no artifact of its own; its result is recorded elsewhere.
            </p>
          ) : (
            <ul className="rail-outputs">
              {stage.outputs.map((slot) => (
                <Artifact key={slot.path} slot={slot} course={course} />
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </li>
  )
}
