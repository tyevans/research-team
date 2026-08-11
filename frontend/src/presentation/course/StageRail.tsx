import clsx from 'clsx'

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
      {/* The count is expanded in the row's own accessible name rather than in
          a tooltip, and the choice is forced: this row is a `<button>`, and
          `Tooltip`'s wrapper is another one. "4/6" and "—" are the two things
          on this row a reader cannot expand for themselves, so they are said
          in full here — which also replaces what the two `title`s carried, for
          a reader the `title`s never reached. */}
      <button
        type="button"
        className="rail-row"
        aria-expanded={open}
        aria-label={`Stage ${stage.index}: ${stage.name}, ${stage.status}, ${
          stage.outputs.length > 0
            ? `${written} of ${stage.outputs.length} declared artifacts written`
            : 'declares no artifact of its own'
        }`}
        onClick={onToggle}
      >
        <span className={`rail-dot rail-${stage.status}`} aria-hidden="true" />
        <span className="rail-index">{stage.index}</span>
        <span className="rail-name">{stage.name}</span>
        {/* Written-of-declared, not a percentage: a stage owing two artifacts
            with one written is a specific situation, and "50%" is not. */}
        {stage.outputs.length > 0 ? (
          <span
            // `clsx` for the same reason as `Artifacts.tsx`: the plugin eats
            // the leading space in a template literal's conditional branch.
            className={clsx('rail-count', written < stage.outputs.length && 'rail-short')}
          >
            {written}/{stage.outputs.length}
          </span>
        ) : (
          <span className="rail-count empty">—</span>
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
