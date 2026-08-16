/** Discovered classes, and the fold that makes them judgeable.
 *
 * A pure module: no fetching, no React, no store -- the shape `graph.ts` uses,
 * and for the same reason. The ordering rule below is a correctness property
 * that is easy to lose under refactoring pressure from a caller.
 *
 * Everything here is *derived*: a model read a document and proposed these
 * groupings. So the fold's job is not to present them but to keep the reader
 * able to check them -- which is why `complete` is computed and surfaced
 * rather than resolved away, and why rejections travel with the class that
 * lost them.
 */

/** One member of a class, as the document spelled it. */
export interface OntologyMember {
  readonly name: string
  /** Position in an ordered scale, counting from 0, or `null` in a set.
   *
   * Not derived from array order: a reader who saw an unordered set sorted by
   * arrival would be reading a sequence into a bag, so the *absence* of an
   * ordinal has to survive the wire. */
  readonly ordinal: number | null
}

/** A member the model proposed and verification refused, with the reason. */
export interface RejectedMember {
  readonly name: string
  readonly reason: string
}

/** Where in a source document the class was stated. */
export interface Evidence {
  readonly sourceId: string
  readonly start: number
  readonly end: number
}

export type OntologyKind = 'ordered_scale' | 'unordered_set' | 'taxonomy'

export interface OntologyClass {
  readonly id: string
  readonly name: string
  readonly kind: OntologyKind
  /** The count the document stated, or `null` when it stated none.
   *
   * A claim to check the members against, not a length. Most documents name a
   * group without counting it, so `null` is the ordinary case. */
  readonly declaredCount: number | null
  readonly members: readonly OntologyMember[]
  readonly rejectedMembers: readonly RejectedMember[]
  readonly evidence: Evidence
  readonly parentClassId: string | null
  /** Whether the graph beneath this class has moved since it was found. */
  readonly stale: boolean
  /** Whether the members found match the count the document stated.
   *
   * `true` when no count was stated -- there is nothing to disagree with, and
   * marking every uncounted class incomplete would make the flag meaningless
   * on the majority of classes. Computed here rather than at each render, so
   * one rule decides it. */
  readonly complete: boolean
}

/** The API's shape, before it is folded. Snake_case is the wire's, not ours. */
export interface OntologyPayload {
  readonly classes: readonly {
    readonly id: string
    readonly name: string
    readonly kind: string
    readonly declaredCount: number | null
    readonly memberCount: number
    readonly parentClassId: string | null
    readonly evidence: Evidence
    readonly rejectedMembers: readonly RejectedMember[]
    readonly stale: boolean
    readonly members: readonly { readonly name: string; readonly ordinal: number | null }[]
  }[]
}

const KINDS: readonly string[] = ['ordered_scale', 'unordered_set', 'taxonomy']

/** An unrecognised `kind` reads as an unordered set.
 *
 * The server already refuses one it does not know (`verify_classes`), so this
 * is unreachable through the ordinary path and exists so a future server
 * vocabulary does not crash an older bundle. `unordered_set` is the safe
 * landing: it is the only kind that asserts nothing the text may not have
 * said, where `ordered_scale` would claim an ordering. */
const asKind = (raw: string): OntologyKind =>
  KINDS.includes(raw) ? (raw as OntologyKind) : 'unordered_set'

/** Members in the order the class should be read in.
 *
 * An ordered scale sorts by ordinal, because the ordinal is the information --
 * `D C B A S` is not alphabetical, not the order it arrived in, and not
 * recoverable from anything else on the row. Everything else keeps arrival
 * order untouched: sorting a bag would invent a sequence, and sorting it by
 * name would invent one that looks deliberate.
 *
 * Members with no ordinal sort last within a scale rather than to the front,
 * so a partially-numbered scale still reads from its known end. */
const inReadingOrder = (
  kind: OntologyKind,
  members: readonly OntologyMember[],
): readonly OntologyMember[] => {
  if (kind !== 'ordered_scale') return members
  return [...members].sort((left, right) => {
    if (left.ordinal === null) return right.ordinal === null ? 0 : 1
    if (right.ordinal === null) return -1
    return left.ordinal - right.ordinal
  })
}

export const foldOntology = (payload: OntologyPayload): readonly OntologyClass[] =>
  payload.classes.map((raw) => {
    const kind = asKind(raw.kind)
    return {
      id: raw.id,
      name: raw.name,
      kind,
      declaredCount: raw.declaredCount,
      members: inReadingOrder(kind, raw.members),
      rejectedMembers: raw.rejectedMembers,
      evidence: raw.evidence,
      parentClassId: raw.parentClassId,
      stale: raw.stale,
      // Against the members actually returned, not the server's `memberCount`.
      // The two agree today; if they ever stop, the list in front of the
      // reader is the honest thing to check a stated count against.
      complete: raw.declaredCount === null || raw.declaredCount === raw.members.length,
    }
  })

/** Classes that nest under `parentId`, or the top level when it is `null`. */
export const childrenOf = (
  classes: readonly OntologyClass[],
  parentId: string | null,
): readonly OntologyClass[] => classes.filter((klass) => klass.parentClassId === parentId)
