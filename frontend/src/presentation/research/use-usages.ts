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
 * mounts this hook earlier does not fire a request for `entityId=null`.
 *
 * `enabled` on top of that is the mentions fold: the section is collapsed when
 * the panel opens, and a passage list nobody has asked to see is a BM25 query
 * per known name (see `UsageReader.usages`) spent on nothing. It is a separate
 * parameter rather than the caller passing `null` for the id, because the id
 * is part of the query key -- collapsing would otherwise move the result to a
 * different cache entry and re-fetch on every expand. */
export const useUsages = (
  projectId: ProjectId,
  entityId: string | null,
  { enabled = true }: { enabled?: boolean } = {},
) => {
  const { usages } = useContainer()

  return useQuery({
    queryKey: queryKeys.usages(projectId, entityId ?? ''),
    queryFn: () => usages.usages(projectId, entityId as string),
    enabled: enabled && entityId !== null,
  })
}
