import type { AreaMember } from './curriculum.ts'

/** Where a card's picture came from. Static art today; `alt` is what a
 *  screen reader gets regardless of what generates the `url` later. */
export interface CandidateArt {
  readonly url: string
  readonly alt: string
}

/** Generated copy, and what it was generated from.
 *
 * `membershipHash` is the hash the *text* was written against -- not the
 * candidate's current one. `blurbAge` below compares the two; carrying both
 * separately is what makes "this copy is N entities behind" checkable rather
 * than assumed, matching `Blurb`'s own docstring server-side
 * (`research_team/domain/course_catalog.py`).
 */
export interface Blurb {
  readonly text: string
  readonly membershipHash: string
  readonly generatedAt: string
}

/** One cluster, dressed for browsing.
 *
 * `blurb` is `null` for a candidate nothing has written copy for yet, which is
 * every candidate on a cold project -- an ordinary state, not a degraded one.
 */
export interface CourseCandidate {
  readonly slug: string
  readonly title: string
  readonly category: string
  readonly prominence: number
  readonly size: number
  /** The area's *current* membership hash. Compared against `blurb`'s own
   *  hash by `blurbAge` to tell "current" from "stale".
   *
   *  Not on the wire today: `candidate_view` in `presenters.py` serializes
   *  `blurb.membershipHash` but never the candidate's own -- so this field
   *  reads `""` from every real response until that presenter gains it, and
   *  `blurbAge` degrades to reporting every blurb as `'stale'` rather than
   *  ever `null`-for-current. Flagged rather than worked around here: fixing
   *  a hash server-side is not this task's shape, and hiding the gap behind a
   *  client-side default would make the missing field invisible again. */
  readonly membershipHash: string
  readonly anchors: readonly AreaMember[]
  readonly art: CandidateArt
  readonly blurb: Blurb | null
  readonly featuredRank: number | null
}

export interface Category {
  readonly key: string
  readonly label: string
  readonly candidates: readonly CourseCandidate[]
}

export interface CatalogSections {
  readonly hero: readonly CourseCandidate[]
  readonly highlights: readonly CourseCandidate[]
  readonly filed: readonly Category[]
}

export interface Catalog {
  readonly sections: CatalogSections
  /** Every category with at least one candidate anywhere in the catalog,
   *  keyed the way `sections.filed` is -- not derived from `filed` alone,
   *  because a category whose every candidate was promoted to hero or
   *  highlights would otherwise have no label anywhere a client can read.
   *  Matches `_every_category` server-side. */
  readonly categories: ReadonlyMap<string, string>
  /** Slugs of featured candidates the current graph has no member for --
   *  re-clustering can move or dissolve an area out from under a feature, and
   *  this is what a curator's page reports rather than silently drops it. */
  readonly unplaceableFeatured: readonly string[]
  readonly derivedFrom: {
    readonly entities: number
    readonly relationships: number
  }
}

/** Whether a candidate's blurb is current, stale, or absent entirely.
 *
 * `null` covers two states the brief's own test cases keep distinct in
 * meaning but not in return value: no blurb at all (ordinary, every candidate
 * on a cold project) and a blurb whose hash still matches (current). Nothing
 * downstream needs to tell those apart today -- a card either has copy to
 * show or it doesn't, and only the second case needs the extra word "stale"
 * appended to it. If a caller later wants "no description yet" rendered
 * differently from "current", check `candidate.blurb === null` directly
 * rather than overloading this return value with a third state.
 *
 * Takes the whole candidate rather than `(candidate, currentHash)`: the
 * candidate already carries its own current `membershipHash`, so a second
 * parameter would just invite a caller to pass the wrong project's hash, or
 * the blurb's own hash back at it, and get a wrong answer with no error to
 * catch it.
 */
export function blurbAge(candidate: CourseCandidate): 'stale' | null {
  if (candidate.blurb === null) return null
  return candidate.blurb.membershipHash === candidate.membershipHash ? null : 'stale'
}
