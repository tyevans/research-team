import type { Course } from '@domain/project/course.ts'

import { Stage } from './StageRail.tsx'

/** Every stage the preset declares, in order, whichever have run.
 *
 * A rail built from what happened can only show what happened, and the
 * question this answers is what was *supposed* to -- which is why the list
 * comes from the preset rather than from the log.
 *
 * Props-only, and the open stage arrives as one rather than being held here.
 * Only one stage opens at a time; a list owning that could not appear twice on
 * a page without the two copies disagreeing, and the page is where the rule
 * "one at a time" actually lives.
 */
export const StageList = ({
  course,
  openStage,
  onToggleStage,
}: {
  course: Course
  openStage: string | null
  onToggleStage: (id: string) => void
}) => (
  <ol className="rail">
    {course.stages.map((stage) => (
      <Stage
        key={stage.id}
        stage={stage}
        course={course}
        open={openStage === stage.id}
        onToggle={() => onToggleStage(stage.id)}
      />
    ))}
  </ol>
)

/** How many stages are behind the project, for the pane's heading.
 *
 * Here rather than inline in the view because the view no longer holds the
 * course's stages -- and because "done" being the only status that counts as
 * left behind is a fact about the domain that two call sites would eventually
 * disagree about.
 */
export const stagesLeftBehind = (course: Course): number =>
  course.stages.filter((stage) => stage.status === 'done').length
