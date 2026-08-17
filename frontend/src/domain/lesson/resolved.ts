import type { GraphNode } from '@domain/knowledge/graph.ts'

import type { ComponentBlock } from './document.ts'

/** A resolved component's reference to one entity, as the author wrote it.
 *
 * `entityId` is an escape hatch and stays on every reference: a human editing
 * a lesson file *can* copy one out of the console, and it is the only way to
 * pin a genuinely ambiguous name. A model cannot write one -- entity ids are
 * opaque UUIDs straight out of redstring's store and nothing derives them
 * from a name -- which is the constraint the whole four-state design exists
 * to absorb.
 */
export interface EntityReference {
  readonly entity: string
  readonly entityId: string | null
}

/** What a reference turned into. Four states, and `ambiguous` is a
 *  first-class one rather than an error.
 *
 * `missing` and `unavailable` must degrade to readable prose, never to an
 * error panel: a model writing about an entity the extraction pipeline has
 * not reached yet is normal, not a defect, and an answer that renders a red
 * box for it is worse than one that renders a word.
 *
 * `loading` is the fifth member and is not in the spec's table, because the
 * table describes outcomes. A renderer still has to draw something while the
 * search is in flight, and folding it into `missing` would flash "not in this
 * project's graph" at a reader on every cold cache.
 */
export type ResolvedEntity =
  | { readonly state: 'loading' }
  | { readonly state: 'resolved'; readonly entity: GraphNode }
  | {
      readonly state: 'ambiguous'
      readonly candidates: readonly GraphNode[]
      /** Whether the server held further matches back beyond `candidates`.
       *
       * Carried rather than dropped because the picker's honesty depends on
       * it: `/graph/entities?name=` caps its page, so "3 entities share that
       * name" is a claim the client cannot make from a capped result. Required
       * rather than optional -- everything that builds one of these is
       * `matchEntities` or a test, both of which can say `false` outright, so
       * there is no legacy construction site to stay lenient for. */
      readonly truncated: boolean
    }
  | { readonly state: 'missing' }
  | { readonly state: 'unavailable' }

const str = (value: unknown): string | null => (typeof value === 'string' ? value : null)

/** The reference out of a component body, defaulting rather than throwing --
 *  the rule every reader in `widgets.ts` follows, for the same reason. */
export const readEntityReference = (block: ComponentBlock): EntityReference => ({
  entity: str(block.data['entity']) ?? '',
  entityId: str(block.data['entity_id']),
})

/** Which of the four states a page of search results puts a name in.
 *
 * The exact-match rule is the load-bearing part. `/graph/entities?name=` is a
 * substring, case-insensitive filter in Python (`graph_reader.py:314`,
 * deliberately not the store's exact `find_entities`), so a search for
 * "Constantine" returns Constantinople as well -- and without preferring the
 * exact hit, the commonest reference a model writes would render a picker
 * every time. Two entities sharing an exact name is the real ambiguity, and
 * the one `entity_id` exists to pin.
 *
 * `truncated` is the caller's `EntitySearchResult.truncated` and is passed
 * through to an `ambiguous` result rather than consulted here. It cannot
 * change which state a page lands in -- an exact hit among the results is
 * still an exact hit whatever the server held back -- but it decides whether
 * the picker may claim to be showing every entity that shares the name. It is
 * dropped on `resolved`, where it would be a claim about a question already
 * answered, and on `missing`, which a truncated search cannot produce.
 */
export const matchEntities = (
  name: string,
  entities: readonly GraphNode[],
  truncated = false,
): ResolvedEntity => {
  if (entities.length === 0) return { state: 'missing' }

  const wanted = name.trim().toLowerCase()
  const exact = entities.filter((entity) => entity.name.trim().toLowerCase() === wanted)
  const candidates = exact.length > 0 ? exact : entities

  const [only] = candidates
  if (candidates.length === 1 && only) return { state: 'resolved', entity: only }
  return { state: 'ambiguous', candidates, truncated }
}
