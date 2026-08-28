import { useQuery, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { useFrameRefresh } from '../shell/use-frame-refresh.ts'

/** Who this project is, and which session holds it.
 *
 * Read from `/api/projects/{id}` rather than from the course, which is where
 * the project page used to get all three of these. The course carries them
 * because it happened to have them; a project that runs no workflow answers
 * 409, and every surface resolved off `holdingSessionId` -- the transcript, the
 * composer, the Workspace tab -- went dark rather than 404ing, which is a
 * symptom nobody would trace back to a course request.
 *
 * `projectName` is `null` until the read settles, and the breadcrumb falls back
 * to a short id for that paint. Deliberately not seeded from the listing: this
 * page is often reached by URL with no listing fetched, so a placeholder from
 * there would be absent exactly when it is wanted.
 */
export const useProject = (projectId: ProjectId) => {
  const { projects } = useContainer()

  const project = useQuery({
    queryKey: queryKeys.project(projectId),
    queryFn: () => projects.project(projectId),
  })
  useProjectRefresh(projectId)

  const holdingSessionId: SessionId | null = project.data?.activeSessionId ?? null

  return { project, projectId, projectName: project.data?.name ?? null, holdingSessionId }
}

/** The holder moves when somebody joins, without a reload.
 *
 * Carried across from `useCourseRefresh` whole, because the subscription is
 * about the project's lifecycle rather than about a run: `ProjectSessionJoined`
 * is the frame that moves the header's "Open holding session" link and the
 * roster, and nothing else fires it.
 *
 * Every project frame rather than a filtered set. They all want this same read,
 * so filtering by `change` would be a list to maintain for no fewer requests.
 *
 * Scoped to `projectId` off the frame's own project id, the way the corpus
 * query scopes a corpus frame -- a project frame names its project because a
 * project's aggregate id *is* the project id. Another project's frames change
 * nothing here.
 *
 * Deliberately not subscribing to log frames: a turn on the holding session
 * writes files, and none of the three fields this hook exposes is a file.
 */
const useProjectRefresh = (projectId: ProjectId) => {
  const queryClient = useQueryClient()

  useFrameRefresh(
    // Always on: this hook lives in the view it refreshes, so being mounted is
    // the "on screen" test `useTreeRefresh` needs its flag for.
    true,
    (frame) => frame.kind === 'project' && frame.projectId === projectId,
    () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) })
      // The header's "Open holding session" link and the roster both come off
      // a project's lifecycle events, and `ProjectSessionJoined` is the frame
      // that moves them. One frame, two reads -- cheaper than two
      // subscriptions that would each fire on all of them anyway.
      void queryClient.invalidateQueries({ queryKey: queryKeys.workers(projectId) })
      // `queryKeys.projects()` is deliberately not invalidated here, and the
      // argument is the one `useCourseRefresh` already made: the list is the
      // landing page's data, this hook is only mounted on a project page, and
      // marking it stale there costs O(projects) of server-side fold for a row
      // with no visible reader. The agent dock is the one exception, and it
      // reads project *names*, which a project frame does not move.
    },
  )
}
