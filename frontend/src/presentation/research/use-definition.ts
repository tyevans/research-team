import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { ProjectId } from '@domain/shared/identifier.ts'

/** An entity's generated definition, fetched through the centralised key for
 *  `useUsages`'s own reason: a prop-drilled definition would never exercise
 *  `queryKeys.definition`, so a misspelled invalidation would go untested.
 *
 * A separate hook and a separate query from `useUsages`, not a combined
 * fetch, because the two answer at different speeds for different reasons --
 * `usages` is a BM25 lookup over the corpus, `definition` is a cache read
 * that falls back to an agent call on a miss -- and folding them into one
 * request would make the fast one wait on the slow one every time either was
 * cold. `GraphDetail.tsx` renders the passages off `useUsages` regardless of
 * how this one is doing.
 *
 * "Show the stale text while a regeneration is in flight" needs no code
 * here beyond the default `useQuery` behaviour: TanStack Query keeps a
 * query's last resolved `data` on screen through a refetch on the same key
 * and only clears it when the key itself changes (a different `entityId`),
 * which is exactly the boundary this panel wants -- the previous entity's
 * definition must not bleed into the newly selected one. See
 * `GraphDetail.tsx` for how `data.stale` becomes the "updating" indicator
 * that tells a reader *why* the text on screen might already be behind. */
export const useDefinition = (projectId: ProjectId, entityId: string | null) => {
  const { definitions } = useContainer()

  return useQuery({
    queryKey: queryKeys.definition(projectId, entityId ?? ''),
    queryFn: () => definitions.definition(projectId, entityId as string),
    enabled: entityId !== null,
  })
}
