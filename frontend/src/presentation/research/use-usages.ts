import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { ProjectId } from '@domain/shared/identifier.ts'

/** The passages an entity is mentioned in, fetched through the centralised
 *  key rather than prop-drilled in from a parent -- `GraphPane` already holds
 *  `projectId` and the selected id, but a component that only ever received
 *  usages as a prop would never exercise `queryKeys.usages` itself, and an
 *  invalidation that misspelled the key would go untested for exactly the
 *  reason `keys.ts`'s own docstring warns about.
 *
 * `enabled: entityId !== null` rather than a caller-side conditional render:
 * `GraphDetail` already returns `null` before this hook would run when there
 * is no selection, but keeping the guard here too means a future caller that
 * mounts this hook earlier does not fire a request for `entityId=null`. */
export const useUsages = (projectId: ProjectId, entityId: string | null) => {
  const { usages } = useContainer()

  return useQuery({
    queryKey: queryKeys.usages(projectId, entityId ?? ''),
    queryFn: () => usages.usages(projectId, entityId as string),
    enabled: entityId !== null,
  })
}
