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
 *
 * **`open` is the route's `artifact` id, and it was not reaching here.**
 * `#/p/<id>/artifact/<path>` has parsed, landed on `selection` and reached
 * MATERIAL since slice 0, and the tab then rendered `<ArtifactList course=…/>`
 * with the id dropped on the floor -- a linkable state that opens the right tab
 * and forgets which row the link was about. The plan's §1 called this "a
 * precondition that is met"; it was met for `stage` only. Defaulted to `null`
 * because `StageRail` renders `Artifact` rows too and has no selection of its
 * own to pass.
 *
 * Matched on `slot.path`, which is what `routes.test.ts` has always encoded
 * (`/artifact/plan.md`) and is the only id an artifact has -- `ArtifactSlot`
 * carries no key of its own.
 */
export const ArtifactList = ({ course, open = null }: { course: Course; open?: string | null }) => {
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
    // `m-0` and `p-0` explicitly, not as tidiness: this build imports no
    // Tailwind preflight, so a `<ul>` keeps the user agent's 16px block margin
    // and 40px inline padding unless something says otherwise. `.artifacts`
    // said so; these say so now.
    <ul className="m-0 list-none p-0">
      {slots.map((slot) => (
        <Artifact key={slot.path} slot={slot} course={course} open={slot.path === open} />
      ))}
    </ul>
  )
}
