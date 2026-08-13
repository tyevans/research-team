import { errorMessage } from '@application/ports/errors.ts'
import { allArtifacts, writtenCount, type Course } from '@domain/project/course.ts'
import type { ProjectId, SessionId } from '@domain/shared/identifier.ts'
import { useSplitPanes } from '@presentation/layout/use-split-panes.ts'

import { EmptyState, Loading } from '../common/primitives.tsx'
import { Pane } from '../layout/Pane.tsx'
import { Split } from '../layout/Split.tsx'
import { projectHref, sessionHref } from '../routing/routes.ts'
import { ArtifactList } from './ArtifactList.tsx'
import { AutonomyPanel } from './AutonomyPanel.tsx'
import { ExtractionPane } from './ExtractionPane.tsx'
import { Findings } from './Findings.tsx'
import { RunPanel } from './RunPanel.tsx'
import { StageList, stagesLeftBehind } from './StageList.tsx'
import { WorkerDrawer } from './WorkerDrawer.tsx'
import { Workers } from './Workers.tsx'
import { COURSE_GROUP, COURSE_TRACKS, useCourse } from './use-course.ts'

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
  openStage,
  onToggleStage,
}: {
  projectId: ProjectId
  /** Reported upward because the breadcrumb wants the project's name and this
   *  is the request that already has it. */
  onLoaded?: (course: Course | null) => void
  /** The session whose transcript the drawer shows, or null. Owned by the
   *  route, not by this view — see `Route`'s `course` variant. */
  watching: SessionId | null
  onWatch: (sessionId: SessionId | null) => void
  /** The open stage, owned by the route for the same reason the watched
   *  session is — see `Route`'s `stage` facet. */
  openStage: string | null
  onToggleStage: (stageId: string) => void
}) => {
  const { course } = useCourse(projectId, onLoaded)
  const panes = useSplitPanes(COURSE_GROUP)

  return (
    <section className="view view-course">
      <div className="view-head">
        <div>
          <h1>{course.data?.preset.name ?? 'Course'}</h1>
          <p className="sub">{course.data ? subtitle(course.data) : ''}</p>
        </div>
        <div className="view-head-actions">
          {/* The graph facet with nothing selected: same page, empty canvas.
              There is no longer a "research page" to link to — there is a
              project, and this asks it for a different facet of itself. */}
          <a className="btn btn-quiet" href={projectHref(projectId, { facet: 'entity', id: null })}>
            Research
          </a>
          <a className="btn btn-quiet" href={projectHref(projectId, { facet: 'ask', id: null })}>
            Ask
          </a>
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
          <EmptyState heading="No course to show." detail={errorMessage(course.error)} />
        </div>
      ) : course.isPending ? (
        <Loading what="course" />
      ) : (
        <>
          <div className="course-findings">
            <Findings course={course.data} />
          </div>
          {/* Two peer columns, which is exactly what `Split` is for -- and
              what the page had, declared twice: `.panes` in `panes.css` set
              `display: grid` and `.course-panes` in `course.css` set the
              tracks, so neither file described the grid on its own.
              `panes.css` said so in a comment and named this migration as
              when the pair would go. It has.

              Collapsing is new here, and it comes with the primitive rather
              than being added: a `Split` gives every `Pane` in it a toggle.
              It is worth having on a page whose two lists are read against
              each other -- a rail of twelve stages beside forty artifact rows
              is a lot of scrolling to compare two things -- and `Split`
              refuses to fold the last open one, which is the right rule for
              two columns that both fill the width. */}
          <Split
            id="course"
            label="Course panes"
            tracks={COURSE_TRACKS}
            collapsed={panes.collapsed}
            onCollapsedChange={panes.onCollapsedChange}
            onRefuse={panes.onRefuse}
          >
            <Pane
              id="stages"
              label="Stages"
              meta={`${String(stagesLeftBehind(course.data))} of ${String(course.data.stageCount)} left behind`}
            >
              <StageList course={course.data} openStage={openStage} onToggleStage={onToggleStage} />
            </Pane>

            <Pane
              id="artifacts"
              label="Artifacts"
              meta={`${String(writtenCount(allArtifacts(course.data)))} of ${String(allArtifacts(course.data).length)} written`}
            >
              <ArtifactList course={course.data} />
            </Pane>
          </Split>
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
