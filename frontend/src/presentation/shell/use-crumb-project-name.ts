import { useQuery } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import type { Route } from '../routing/routes.ts'

/** Which project the breadcrumb is standing in, or `null` for a route that is
 *  in no project.
 *
 * Two routes carry one, and the second is the reason this function exists:
 * `#/settings/project/<id>` is a page *about* a project that does not render
 * the project, so the name cannot come from the view the way it used to. */
export const crumbProjectId = (route: Route): ProjectId | null => {
  if (route.name === 'project') return route.id
  if (route.name === 'settings' && route.scope === 'project') return ProjectId(route.scopeId)
  return null
}

/** The project name the trail should show, or `null` until the read settles.
 *
 * This replaces an `onLoaded` callback that `ProjectView` fired into a
 * `useState` in `App`, and the replacement is not a refactor for its own sake:
 * that path could only ever name a project whose view was *mounted*, and the
 * settings page mounts no project view. Pushing the name up from the one view
 * that happened to have it made the crumb a property of what was on screen
 * rather than of the route, which is the wrong thing for a trail to be.
 *
 * No extra request on a project page. This is `queryKeys.project(id)` --
 * the same key `useProject` reads -- so React Query serves both from one
 * fetch, and on the settings page it is the only reader.
 */
export const useCrumbProjectName = (route: Route): string | null => {
  const { projects } = useContainer()
  const projectId = crumbProjectId(route)

  const project = useQuery({
    // Never called while `projectId` is null, because `enabled` is false --
    // the placeholder only has to be a stable key, not a real id.
    queryKey: queryKeys.project(projectId ?? ProjectId('no-project')),
    queryFn: () => projects.project(projectId as ProjectId),
    enabled: projectId !== null,
  })

  return project.data?.name ?? null
}
