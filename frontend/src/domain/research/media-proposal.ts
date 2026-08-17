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

/** What to tell a person about one curation run.
 *
 * A bare "no media candidates found" is the message this replaced, and it
 * was true but useless: the chain has four distinct routes to zero, and that
 * sentence named none of them. Measured on 2026-08-16 -- a woodworking topic
 * produced two well-formed needs and zero candidates, and answering "which
 * stage failed?" took reading the source, querying the SearXNG instance by
 * hand, and finally the event log, because the toast and the response body
 * between them carried nothing that distinguished the cases.
 *
 * So the zero case reports the counts that explain it. The order is the
 * chain's own: what the search never found, what the ignore list removed,
 * what could not be read. Only non-zero counts appear -- a run that found
 * nothing for an ordinary reason should not read like a list of faults.
 */
export function curationSummary(outcome: {
  readonly needs: number
  readonly candidates: number
  readonly ignored: number
  readonly rejectedParses: number
  readonly searchedEmpty: number
}): string {
  // `many` is explicit rather than `word + 's'` because "reply" pluralises to
  // "replies" and the naive rule wrote "replys" -- caught by the test, which
  // is the only reason this parameter exists.
  const plural = (n: number, word: string, many = `${word}s`) => `${n} ${n === 1 ? word : many}`
  if (outcome.candidates > 0) {
    return `Found ${plural(outcome.candidates, 'media candidate')} across ${plural(outcome.needs, 'need')}.`
  }
  const because = [
    outcome.searchedEmpty > 0 ? `${plural(outcome.searchedEmpty, 'need')} found nothing` : null,
    outcome.ignored > 0 ? `${outcome.ignored} ignored` : null,
    outcome.rejectedParses > 0
      ? plural(outcome.rejectedParses, 'unreadable reply', 'unreadable replies')
      : null,
  ].filter((part): part is string => part !== null)
  const detail = because.length > 0 ? `; ${because.join(', ')}` : ''
  return `No media candidates found (${plural(outcome.needs, 'need')} identified${detail}).`
}
