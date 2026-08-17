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
  | { readonly state: 'ambiguous'; readonly candidates: readonly GraphNode[] }
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
 */
export const matchEntities = (name: string, entities: readonly GraphNode[]): ResolvedEntity => {
  if (entities.length === 0) return { state: 'missing' }

  const wanted = name.trim().toLowerCase()
  const exact = entities.filter((entity) => entity.name.trim().toLowerCase() === wanted)
  const candidates = exact.length > 0 ? exact : entities

  const [only] = candidates
  if (candidates.length === 1 && only) return { state: 'resolved', entity: only }
  return { state: 'ambiguous', candidates }
}
