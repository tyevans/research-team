import { useQuery, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { useFrameRefresh } from '../shell/use-frame-refresh.ts'

/** Who this project is, which session holds it, and which one to read it
 *  through.
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

  /** Which session this project's *files* are read through, which is not the
   *  same question as who holds it.
   *
   * Equal to `holdingSessionId` while somebody holds the project, and the tip
   * session between sessions -- resolved server-side, because the tip session
   * is not on the wire and a client cannot compute the fallback itself. The
   * two came apart precisely where the console used to go dark: a project
   * nobody was holding had files and no session id to read them through, so
   * the workspace showed an empty state and the Workspace tab was hidden on
   * exactly that condition.
   *
   * `null` is a project nothing has ever been written in. Callers keyed on a
   * session id must check this rather than `holdingSessionId` -- a surface
   * that reads the holder is asking "who is driving", and the surfaces here
   * are almost all asking "what is there to read".
   */
  const readingHeadSessionId: SessionId | null = project.data?.readingHeadSessionId ?? null

  return {
    project,
    projectId,
    projectName: project.data?.name ?? null,
    holdingSessionId,
    readingHeadSessionId,
  }
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
 * writes files, and none of the fields this hook exposes is a file. That
 * sentence is one field closer to untrue than it was -- `readingHeadSessionId`
 * is what a file tree is read through -- but it is still a session *id*, and
 * an id does not move when a turn writes into it. The day this hook carries a
 * file list is the day that changes.
 */
const useProjectRefresh = (projectId: ProjectId) => {
  const queryClient = useQueryClient()

  useFrameRefresh(
    // Always on: this hook lives in the view it refreshes, so being mounted is
    // the "on screen" test `useTreeRefresh` needs its flag for.
    true,
    (frame) => frame.kind === 'project' && frame.projectId === projectId,
    () => {
      // The header's "Open holding session" link comes off a project's
      // lifecycle events, and `ProjectSessionJoined` is the frame that moves
      // it. The roster used to read off this same frame too -- one frame, two
      // reads -- but the roster is gone (Task 2 of the activity-placement
      // plan: a per-project poll of what the agent dock already answers for
      // everything, for free). This invalidation is still worth the
      // subscription on its own: it is the only thing that moves the link
      // without a reload.
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) })
      // `queryKeys.projects()` is deliberately not invalidated here, and the
      // argument is the one `useCourseRefresh` already made: the list is the
      // landing page's data, this hook is only mounted on a project page, and
      // marking it stale there costs O(projects) of server-side fold for a row
      // with no visible reader. The agent dock is the one exception, and it
      // reads project *names*, which a project frame does not move.
    },
  )
}
