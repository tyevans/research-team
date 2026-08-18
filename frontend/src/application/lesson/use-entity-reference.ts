import { useQuery } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import { resolvedWidgetQuery } from '@application/queries/resolved-widget.ts'
import type { EntityReference, ResolvedEntity } from '@domain/lesson/resolved.ts'
import { matchEntities } from '@domain/lesson/resolved.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

/** A resolved component's reference, turned into one of five render states.
 *
 * Three of the five never reach the network:
 *
 *  - no `projectId` -> `unavailable`, **including for a pinned `entity_id`**.
 *    A course file is read from a session,
 *    which has no project in scope (`LessonDocument.tsx:48`), and that is a
 *    real case rather than a misuse. Calling the port with `undefined` would
 *    produce a request against a URL with the word "undefined" in it and
 *    report a network failure where the honest answer is "this page cannot
 *    look that up".
 *  - an `entityId` *with* a project -> `resolved` immediately, on a
 *    synthesised node carrying
 *    the author's name. The escape hatch is exact by construction and
 *    confirming it would cost a request to learn nothing. The cost, stated:
 *    `entityType` is empty, so a frame that renders the type shows nothing
 *    for a pinned reference. That is the trade the escape hatch makes.
 *  - an empty name -> `unavailable`. `entity:` absent is already a validation
 *    error the server reported; searching for "" would ask for the graph.
 *
 * A rejected search is `unavailable`, never `missing`. 503 (nothing wired)
 * and "no such entity" say opposite things about the corpus, and a reader
 * told "not in this project's graph" by a server that never looked has been
 * told something false.
 */
export const useEntityReference = (
  projectId: ProjectId | undefined,
  reference: EntityReference,
): ResolvedEntity => {
  const { graphs } = useContainer()
  const name = reference.entity.trim()
  const enabled = Boolean(projectId) && name.length > 0 && reference.entityId === null

  const search = useQuery({
    queryKey: queryKeys.entityReference(projectId ?? ('' as ProjectId), name),
    queryFn: () => graphs.search(projectId as ProjectId, name),
    enabled,
    // One policy for every resolved widget; the reasoning is in the constant.
    ...resolvedWidgetQuery,
  })

  // No project outranks a pinned id, and the order of these two lines is the
  // whole of that rule. Reversed, a hand-edited lesson file read outside any
  // project answered `resolved` with an id the page cannot fetch anything
  // with, and `DefinitionWidget`/`GraphWidget` -- which need a `projectId` to
  // mount their inner fetch -- drew nothing at all. Spec §1 requires
  // `unavailable` to degrade to readable prose, never to nothing.
  // `use-entity-reference.test.tsx`'s pinned-id-with-no-project case fails if
  // these swap back.
  if (projectId && reference.entityId !== null) {
    return {
      state: 'resolved',
      entity: { id: reference.entityId, name: reference.entity, entityType: '' },
    }
  }
  if (!enabled) return { state: 'unavailable' }
  if (search.isError) return { state: 'unavailable' }
  if (!search.data) return { state: 'loading' }
  return matchEntities(name, search.data.entities, search.data.truncated)
}
