import { allArtifacts, type Course } from '@domain/project/course.ts'

import { EmptyState } from '../common/primitives.tsx'
import { Artifact } from './Artifacts.tsx'

/** Every artifact the workflow declares, written or not.
 *
 * The missing ones are the point: a list of files that exist answers "what is
 * there", and the question this page is for is "what was promised". Missing
 * rows are dimmed by `Artifacts.tsx` rather than hidden or reddened -- hidden
 * loses the gap the view exists to surface, and red calls it a failure, which
 * is a verdict, and verdicts belong to the check library.
 *
 * `allArtifacts` is called once here rather than three times as it was at the
 * old call site -- twice for the heading's counts and once for the rows, on
 * every render, each rebuilding the same array.
 */
export const ArtifactList = ({ course }: { course: Course }) => {
  const slots = allArtifacts(course)

  if (slots.length === 0) {
    return (
      <EmptyState
        heading="This workflow declares no artifacts."
        detail="Nothing here is missing; the preset simply names no outputs."
      />
    )
  }

  return (
    <ul className="artifacts">
      {slots.map((slot) => (
        <Artifact key={slot.path} slot={slot} course={course} />
      ))}
    </ul>
  )
}
