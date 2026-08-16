import type { SourceId } from '../shared/identifier.ts'

/** Where one proposal sits in its lifecycle -- `decide`'s own transition
 *  table in `domain/media_proposals.py`, restated as a union rather than a
 *  bare `string` so a component's `switch` is exhaustive and a typo in a
 *  case label is a compile error, not a proposal that renders no action at
 *  all. */
export type MediaProposalStatus = 'proposed' | 'accepted' | 'rejected' | 'stored' | 'failed'

/** One candidate for one need: what it is, why it was proposed, and how far
 *  it has gotten toward being a stored source.
 *
 * `sourceId` and `error` are the two outcomes `stored`/`failed` can reach --
 * mutually exclusive on the wire and both nullable here for the same reason
 * `MediaProposalRow`'s own docstring gives: the domain aggregate is what
 * enforces that they are never both set, not this shape.
 */
export interface MediaProposal {
  readonly proposalId: string
  readonly needId: string
  readonly topicId: string
  readonly pageUrl: string
  readonly assetUrl: string
  /** `null` when the search result carried none -- 46 of 262 image results,
   *  measured. A card renders a typed placeholder for this case rather than
   *  falling back to `assetUrl`; see `MediaProposalCard`'s own comment for
   *  why that fallback is the wrong default, not just an unbuilt one. */
  readonly thumbnailUrl: string | null
  readonly kind: string
  readonly title: string
  readonly reason: string
  readonly query: string
  readonly status: MediaProposalStatus
  readonly note: string
  readonly sourceId: SourceId | null
  readonly error: string | null
}

/** One need's proposals, labelled with the sentence that produced them.
 *
 * `needDescription` is what a person judges a proposal against -- see the
 * pane's own reasoning -- so it travels with the group rather than being
 * looked up per card from a second list the card would have to be handed. */
export interface MediaProposalGroup {
  readonly needId: string
  readonly needDescription: string
  readonly proposals: readonly MediaProposal[]
}

/** Both ignore lists at once, matching `GET .../ignored`'s own shape --
 *  the pane that shows one shows both, so splitting this into two reads
 *  would be two requests for one screen. */
export interface IgnoredMedia {
  readonly assets: readonly string[]
  readonly hosts: readonly string[]
}
