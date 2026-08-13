import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { Course } from '@domain/project/course.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'
import type { Track } from '@presentation/layout/split-tracks.ts'

import { useFrameRefresh } from '../shell/use-frame-refresh.ts'

/** Which view's layout this is. See `use-session-panes.ts`: the group is what
 *  keeps three views' stored layouts apart. */
export const COURSE_GROUP = 'course'

/** The course page's two columns, as data.
 *
 * The same numbers `.course-panes` carried, and taken from there rather than
 * chosen: `minmax(0, 1fr) minmax(0, 1.2fr)`. The artifact list is the wider of
 * the two because its rows carry a provenance line and the rail's carry a
 * name and a count.
 *
 * A `min` of 0 rather than a pixel floor, also unchanged. This page scrolls,
 * so a column that becomes too narrow to read reflows rather than forcing a
 * horizontal scrollbar on the whole page, and a floor here would produce the
 * second thing.
 */
export const COURSE_TRACKS: readonly Track[] = [
  { id: 'stages', min: 0, weight: 1 },
  { id: 'artifacts', min: 0, weight: 1.2 },
]

/** The course.
 *
 * `openStage` used to live here, with an argument against routing it: "an
 * opened stage is a glance, not a place, and putting it in the address bar
 * would make every glance a history entry." The first half was wrong and the
 * second half had an answer already in the codebase. A reader who has found the
 * stage whose gate is blocking a project wants to send *that*, which is exactly
 * what a place is; and `navigate(..., { replace: true })` -- what scrubbing and
 * the graph's entity selection both use -- puts it in the address bar without
 * putting it in the back stack. So it is `App.tsx`'s now, off `Route`'s `stage`
 * facet, and a course page deep-linked to a stage no longer loads collapsed.
 */
export const useCourse = (projectId: ProjectId, onLoaded?: (course: Course | null) => void) => {
  const { projects } = useContainer()

  const course = useQuery({
    queryKey: queryKeys.course(projectId),
    queryFn: () => projects.course(projectId),
    retry: false,
  })
  useCourseRefresh(projectId)

  useEffect(() => {
    onLoaded?.(course.data ?? null)
    return () => onLoaded?.(null)
  }, [course.data, onLoaded])

  return { course }
}

/** The rail moves when the project does, without a reload.
 *
 * It did not, and that was the whole of the reported bug: `advance_stage`
 * appended `ProjectStageAdvanced` and this page showed the old stage until somebody
 * refreshed. The missing half was on the server -- the feed filtered `Project`
 * streams out, so no frame ever arrived -- but a subscription had to exist
 * here too, and none did.
 *
 * Every project frame, not only a stage advance. `ProjectWorkflowSelected` is what
 * turns this page from "No course to show" into a rail, and the lifecycle
 * events move the holding-session link in the header; they all want this same
 * read, so filtering by `change` would be a list to maintain for no fewer
 * requests.
 *
 * Scoped to `projectId` off the frame's own project id, the way the corpus
 * query scopes a corpus frame -- a project frame names its project because a
 * project's aggregate id *is* the project id. Another project's advance
 * changes nothing here.
 *
 * Deliberately not subscribing to log frames. A turn on the holding session
 * writes files, and a written file can fill an artifact slot the rail draws --
 * but refetching the course on every token of every turn is the cost the
 * corpus query refused for the same reason, and the artifact list is one stage
 * boundary behind at worst. If that becomes the complaint, the answer is a
 * narrower frame from the server, not this hook widening.
 */
const useCourseRefresh = (projectId: ProjectId) => {
  const queryClient = useQueryClient()

  useFrameRefresh(
    // Always on: this hook lives in the view it refreshes, so being mounted is
    // the "on screen" test `useTreeRefresh` needs its flag for.
    true,
    (frame) => frame.kind === 'project' && frame.projectId === projectId,
    () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.course(projectId) })
      // The header's "Open holding session" link and the roster both come off
      // a project's lifecycle events, and `ProjectSessionJoined` is the frame
      // that moves them. One frame, three reads -- cheaper than three
      // subscriptions that would each fire on all of them anyway.
      void queryClient.invalidateQueries({ queryKey: queryKeys.workers(projectId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects() })
    },
  )
}
