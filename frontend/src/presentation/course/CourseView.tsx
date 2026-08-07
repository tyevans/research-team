import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import {
  allArtifacts,
  severityLabel,
  writtenCount,
  type ArtifactSlot,
  type Course,
  type Provenance,
  type SourceSpan,
  type StageProgress,
} from '@domain/project/course.ts'
import { formatSpan } from '@domain/project/course.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Chip, EmptyState, Loading } from '../common/primitives.tsx'
import { sessionHref } from '../routing/routes.ts'
import { RunPanel } from './RunPanel.tsx'

/** The run seen whole: what the workflow was supposed to produce, and what it
 *  has.
 *
 * Two panes rather than one list, because the rail answers "where are we" and
 * the artifact list answers "what is there", and a reader scanning for one
 * should not have to read the other.
 */
export const CourseView = ({
  projectId,
  onLoaded,
}: {
  projectId: ProjectId
  /** Reported upward because the breadcrumb wants the project's name and this
   *  is the request that already has it. */
  onLoaded?: (course: Course | null) => void
}) => {
  const { projects } = useContainer()
  const [openStage, setOpenStage] = useState<string | null>(null)

  const course = useQuery({
    queryKey: queryKeys.course(projectId),
    queryFn: () => projects.course(projectId),
    retry: false,
  })

  useEffect(() => {
    onLoaded?.(course.data ?? null)
    return () => onLoaded?.(null)
  }, [course.data, onLoaded])

  return (
    <section className="view view-course">
      <div className="view-head">
        <div>
          <h1>{course.data?.preset.name ?? 'Course'}</h1>
          <p className="sub">{course.data ? subtitle(course.data) : ''}</p>
        </div>
        <div className="view-head-actions">
          {course.data?.holdingSessionId ? (
            <a className="btn btn-quiet" href={sessionHref(course.data.holdingSessionId)}>
              Open holding session
            </a>
          ) : null}
        </div>
      </div>

      {/* A run works the project's topic queue, not the workflow's stages, so
          this sits above the course rather than inside it — and renders even
          when the project has no workflow and the panes below have nothing. */}
      <section className="run-panel" aria-label="Autonomous research">
        <RunPanel projectId={projectId} />
      </section>

      {course.isError ? (
        // The two 409s — no workflow, or one this build does not ship — are the
        // interesting failures, and the server's message already names which
        // and what to do about it. Relaying it beats a generic error.
        <div className="course-findings">
          <EmptyState title="No course to show." detail={errorMessage(course.error)} />
        </div>
      ) : course.isPending ? (
        <Loading what="course" />
      ) : (
        <>
          <div className="course-findings">
            <Findings course={course.data} />
          </div>
          <div className="panes course-panes">
            <section className="pane pane-rail" aria-label="Stage rail">
              <header className="pane-head">
                <h2>Stages</h2>
                <span className="pane-meta">
                  {course.data.stages.filter((stage) => stage.status === 'done').length} of{' '}
                  {course.data.stageCount} left behind
                </span>
              </header>
              <div className="pane-body">
                <ol className="rail">
                  {course.data.stages.map((stage) => (
                    <Stage
                      key={stage.id}
                      stage={stage}
                      course={course.data}
                      open={openStage === stage.id}
                      onToggle={() =>
                        setOpenStage((current) => (current === stage.id ? null : stage.id))
                      }
                    />
                  ))}
                </ol>
              </div>
            </section>

            <section className="pane pane-artifacts" aria-label="Artifacts">
              <header className="pane-head">
                <h2>Artifacts</h2>
                <span className="pane-meta">
                  {writtenCount(allArtifacts(course.data))} of {allArtifacts(course.data).length}{' '}
                  written
                </span>
              </header>
              <div className="pane-body">
                {allArtifacts(course.data).length === 0 ? (
                  <EmptyState
                    title="This workflow declares no artifacts."
                    detail="Nothing here is missing; the preset simply names no outputs."
                  />
                ) : (
                  <ul className="artifacts">
                    {allArtifacts(course.data).map((slot) => (
                      <Artifact key={slot.path} slot={slot} course={course.data} />
                    ))}
                  </ul>
                )}
              </div>
            </section>
          </div>
        </>
      )}
    </section>
  )
}

const subtitle = (course: Course): string =>
  course.position !== null
    ? `Stage ${course.position} of ${course.stageCount} · ${course.preset.id} v${course.preset.version}`
    : // No position means the project's recorded stage is not one the preset
      // contains. The rail still renders; saying so is the point.
      `This project’s recorded stage is not part of ${course.preset.id}, so its position is unknown.`

/** What the *current* stage's own checks say, right now.
 *
 * Only the current stage's: a stage that has been left has a findings artifact
 * recorded at the moment it was left, and that record is what its gate decision
 * was made against. Recomputing it against a course that has since grown would
 * show a different table and quietly present it as the one the reviewer saw. */
const Findings = ({ course }: { course: Course }) => {
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

const Stage = ({
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

/** One declared artifact, in one of four states a naive row would flatten into
 *  two: missing; present but with no readable frontmatter; present and claiming
 *  sources; present and claiming its thinking was the model's own. The last two
 *  are both legitimate and must not look alike. */
const Artifact = ({ slot, course }: { slot: ArtifactSlot; course: Course }) => {
  const name = FilePath.of(slot.path).basename
  return (
    <li className={`artifact${slot.present ? '' : ' artifact-missing'}`}>
      <div className="artifact-top">
        <span className="artifact-name">
          {slot.present ? (
            <CourseFileLink course={course} path={slot.path} text={name} />
          ) : (
            <span className="muted">{name}</span>
          )}
        </span>
        <span className="artifact-type">
          {slot.artifactType}
          {slot.subtype ? ` (${slot.subtype})` : ''}
        </span>
        <span className="muted artifact-card">{slot.cardinality}</span>
        {slot.present ? (
          <Chip tone="present">written</Chip>
        ) : (
          <Chip
            tone="missing"
            title={`The preset declares this artifact and no file is at ${slot.path}`}
          >
            not written
          </Chip>
        )}
      </div>

      {slot.present && !slot.hasFrontmatter ? (
        <div className="artifact-note bad">
          No readable frontmatter, so nothing can tell what this is or what it rests on.
        </div>
      ) : slot.present ? (
        <>
          {slot.missingFields.length > 0 ? (
            <div className="artifact-note">
              Frontmatter is missing {slot.missingFields.join(', ')}.
            </div>
          ) : null}
          <ProvenanceRow provenance={slot.provenance} course={course} />
        </>
      ) : null}
    </li>
  )
}

/** What an artifact says it rests on, shown as claims rather than as a score.
 *
 * Spans link into the source reader at the offsets the file claims —
 * unresolved, because whether a span still says what it said is a check's
 * question, and answering it here would cost a document read per row. */
const ProvenanceRow = ({
  provenance,
  course,
}: {
  provenance: Provenance | null
  course: Course
}) => {
  if (!provenance) return <div className="artifact-note">No provenance block at all.</div>

  return (
    <div className="artifact-prov">
      <span className="muted">rests on: </span>
      {provenance.sources.map((span, index) => (
        <a
          key={index}
          className="prov-src"
          href={sourceHref(course, span)}
          title="Open this source at the offsets this artifact cites"
        >
          {formatSpan(span)}
        </a>
      ))}
      {provenance.inferred ? (
        <Chip
          tone="inferred"
          title="Some of this was reasoned rather than drawn from a source, and says so."
        >
          inferred
        </Chip>
      ) : null}
      {provenance.unreadable > 0 ? (
        <Chip
          tone="bad"
          title="Entries that are neither a source span nor the inference flag."
        >
          {provenance.unreadable} unreadable
        </Chip>
      ) : null}
      {provenance.empty ? (
        <Chip
          tone="bad"
          title={
            'Neither a source nor an admission of inference — indistinguishable from an ' +
            'artifact never checked against anything.'
          }
        >
          claims nothing
        </Chip>
      ) : null}
    </div>
  )
}

const sourceHref = (course: Course, span: SourceSpan): string => {
  const base = `/api/projects/${encodeURIComponent(course.projectId)}/sources/${encodeURIComponent(
    span.sourceId,
  )}`
  if (span.start === null || span.end === null) return base
  return `${base}?start=${span.start}&end=${span.end}`
}

/** Course files are read through the session that holds them, because that is
 *  where the file viewer lives and it already renders markdown, diffs and
 *  per-file history. A second reader here would be a worse copy of it. */
const CourseFileLink = ({
  course,
  path,
  text,
}: {
  course: Course
  path: string
  text?: string
}) => {
  const label = text ?? FilePath.of(path).basename
  if (!course.holdingSessionId) {
    return (
      <span
        className="muted"
        title="No session is holding this project, so there is nothing to open the file in. Join the project to read it."
      >
        {label}
      </span>
    )
  }
  return (
    <a href={sessionHref(course.holdingSessionId, undefined, FilePath.of(path))} title={path}>
      {label}
    </a>
  )
}
