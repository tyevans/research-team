import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { allArtifacts, writtenCount, type Course } from '@domain/project/course.ts'
import type { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { EmptyState, Loading } from '../common/primitives.tsx'
import { sessionHref } from '../routing/routes.ts'
import { Artifact } from './Artifacts.tsx'
import { AutonomyPanel } from './AutonomyPanel.tsx'
import { ExtractionPane } from './ExtractionPane.tsx'
import { Findings } from './Findings.tsx'
import { RunPanel } from './RunPanel.tsx'
import { Stage } from './StageRail.tsx'
import { WorkerDrawer } from './WorkerDrawer.tsx'
import { Workers } from './Workers.tsx'

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
  watching,
  onWatch,
}: {
  projectId: ProjectId
  /** Reported upward because the breadcrumb wants the project's name and this
   *  is the request that already has it. */
  onLoaded?: (course: Course | null) => void
  /** The session whose transcript the drawer shows, or null. Owned by the
   *  route, not by this view — see `Route`'s `course` variant. */
  watching: SessionId | null
  onWatch: (sessionId: SessionId | null) => void
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

      {/* Everything currently working on this project, run and turn and
          extraction alike — not just the run's own counters, which say
          nothing about a turn or extraction still in flight. */}
      <section className="worker-panel" aria-label="Working now">
        <Workers projectId={projectId} watching={watching} onWatch={onWatch} />
        {/* The roster row is the summary — "an extraction is running" — and
            this is the detail underneath it. Inside the same panel rather
            than beside it, because a reader who sees the row is asking the
            question this answers. */}
        <ExtractionPane projectId={projectId} />
      </section>

      {/* A run works the project's topic queue, not the workflow's stages, so
          this sits above the course rather than inside it — and renders even
          when the project has no workflow and the panes below have nothing. */}
      <section className="run-panel" aria-label="Autonomous research">
        <RunPanel projectId={projectId} />
      </section>

      {/* A sibling of the run panel rather than a pane inside the course: the
          policy is instance-wide, so it is not a property of this project any
          more than the run is, and burying it under a workflow the project may
          not even have would hide it exactly when somebody is looking for it.
          The holding session is passed because a write has to be recorded
          against somebody's stream — see `AutonomyPanel`. When there is none,
          the panel renders read-only and says why rather than offering
          controls that would 404. */}
      <section className="autonomy-panel" aria-label="Autonomy">
        <AutonomyPanel sessionId={course.data?.holdingSessionId ?? null} />
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

      {watching ? <WorkerDrawer sessionId={watching} onClose={() => onWatch(null)} /> : null}
    </section>
  )
}

const subtitle = (course: Course): string =>
  course.position !== null
    ? `Stage ${course.position} of ${course.stageCount} · ${course.preset.id} v${course.preset.version}`
    : // No position means the project's recorded stage is not one the preset
      // contains. The rail still renders; saying so is the point.
      `This project’s recorded stage is not part of ${course.preset.id}, so its position is unknown.`
