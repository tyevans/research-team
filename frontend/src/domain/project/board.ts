import type { ProjectListing, ProjectSummary } from './project.ts'

/** Arranging projects into the board the index draws.
 *
 * Separate from `landing.ts`, which is about projects *and their sessions* —
 * the forest, the fork lineage, which session to preview. None of that is on
 * the index any more, and none of this is about sessions. Keeping them in one
 * file would have meant one module holding two unrelated arrangements of the
 * same nouns; `landing.ts` is still what the session views use.
 *
 * Pure, and here rather than in a component, for the reason `landing.ts`
 * gives: every question below is about the model. What "how far along" means,
 * what a search matches, and what two projects are ranked on are decisions
 * that must not be answered slightly differently by two call sites.
 */

/** How the board is ordered. */
export type Sort = 'recent' | 'progress' | 'name'

export const SORTS: readonly Sort[] = ['recent', 'progress', 'name']

export const SORT_LABELS: Readonly<Record<Sort, string>> = {
  recent: 'Recent',
  progress: 'Progress',
  name: 'Name',
}

/** The largest value of each stage across the whole board.
 *
 * **This is what makes the bars mean anything.** A bar scaled to its own
 * project's total says only "some", and four of those side by side say
 * nothing a number does not already say better. Scaled to the board's maximum,
 * the same four bars line up into columns down the page, and the comparison a
 * list exists to support — which project has the most sources, which has
 * barely started — is available without reading a single digit.
 *
 * The cost, stated because it is real and a reader cannot see it: the scale is
 * relative, so every bar changes length when a project is added or deleted,
 * and a full bar means "the most here" rather than "a lot". That is the right
 * trade for an index, where the question is always comparative, and it is the
 * wrong one for a project page, where there are no peers to compare against.
 *
 * Floored at 1 so a board where every project has zero sources divides by 1
 * rather than by 0 and draws empty tracks instead of `NaN` widths.
 */
export interface Scale {
  readonly topics: number
  readonly sources: number
  readonly courses: number
}

export const scaleOf = (listings: readonly ProjectListing[]): Scale => ({
  topics: Math.max(1, ...listings.map((one) => one.summary.topics)),
  sources: Math.max(1, ...listings.map((one) => one.summary.sources)),
  courses: Math.max(1, ...listings.map((one) => one.summary.courses)),
})

/** How much of this project's ingest has been folded into the graph, 0–1.
 *
 * 1 for a project with no sources, which is the one case worth arguing:
 * "nothing ingested" is not "extraction is behind", and returning 0 would
 * draw a full amber bar on every empty project — turning the marker for work
 * outstanding into the marker for a project nobody has started. The track is
 * empty in that case anyway, so the value is never drawn; it is defined this
 * way so that `isBehind` below reads correctly rather than needing its own
 * special case.
 */
export const extractedFraction = (summary: ProjectSummary): number =>
  summary.sources === 0 ? 1 : summary.extracted / summary.sources

/** Is there ingested material this project has not extracted?
 *
 * The one thing on this page a reader can act on immediately, and the reason
 * the corpus track is two-tone rather than one bar. Measured against the real
 * database on 2026-08-29: of six projects, two were behind (One Piece at 3 of
 * 6, Intro to Fiction at 9 of 10) and the previous index drew all six
 * identically.
 */
export const isBehind = (summary: ProjectSummary): boolean => summary.sources > summary.extracted

/** How far through the pipeline this project has got, 0–1.
 *
 * **A count of stages reached, not a weighted score**, and that is deliberate.
 * A weighting would have to claim that a source is worth some number of
 * topics, which is not a fact about anything — it would be a number invented
 * in this file and then read off the screen as if it meant something. Counting
 * stages claims only what the pipeline already asserts: that these four things
 * happen in this order, and a project that has done three of them is further
 * along than one that has done two.
 *
 * The extraction stage counts only when extraction is *complete*, which is the
 * one place this is stricter than "has any". A project with 6 sources and 3
 * extracted has begun that stage and not finished it, and the sort should not
 * put it level with one that finished.
 *
 * Used only for ranking, never drawn. There is no progress bar for this number
 * on the page and there should not be: a single "62% done" over four
 * incommensurable stages is exactly the kind of summary that reads as
 * authoritative and means nothing.
 */
export const progressOf = (summary: ProjectSummary): number => {
  const reached =
    Number(summary.topics > 0) +
    Number(summary.sources > 0) +
    Number(summary.sources > 0 && summary.extracted === summary.sources) +
    Number(summary.courses > 0)
  return reached / 4
}

/** Does this project match what was typed?
 *
 * Name only, which is a **deliberate narrowing** from what the previous index
 * searched. That one also matched a session's first message, justified as "the
 * one where I asked about spaced repetition" being a query that works. It did
 * not work: measured against the real database on 2026-08-29, four of six
 * projects opened with the identical string "You are designing a unit by
 * Understanding by Design, Stage 1 only…", because the first message on these
 * sessions is a generated prompt rather than anything a human typed. Searching
 * it matched everything or nothing.
 *
 * The sessions are no longer on this page to search, which is what makes the
 * narrowing free rather than a loss.
 */
export const matches = (listing: ProjectListing, needle: string): boolean => {
  const query = needle.trim().toLowerCase()
  return !query || listing.name.toLowerCase().includes(query)
}

/** The board, filtered and ordered.
 *
 * One function rather than a filter and a sort the caller composes, because
 * the two have to agree about one thing: `sort` is applied to the *filtered*
 * set, so the `progress` order is over what is on screen. A caller that sorted
 * first and filtered second would get the same rows in the same order here and
 * a different answer the moment either step stopped being total.
 *
 * The copy before each sort is not defensive style: `filter` already returns a
 * fresh array, but `shown` is that array and `sort` mutates in place, so a
 * future edit that dropped the filter would be sorting React Query's own
 * cached array — which does not re-render anything, so the list would silently
 * keep whatever order the last sort left. `slice()` makes the copy explicit at
 * every return rather than relying on a property of the line above it.
 */
export const board = (
  listings: readonly ProjectListing[],
  search: string,
  sort: Sort,
): readonly ProjectListing[] => {
  const shown = listings.filter((one) => matches(one, search))
  if (sort === 'name') {
    return shown.slice().sort((a, b) => a.name.localeCompare(b.name))
  }
  if (sort === 'progress') {
    // Ties broken by recency rather than left to the input order, so the
    // board is stable across refetches: four projects at 3/4 would otherwise
    // shuffle whenever the server happened to return them differently.
    return shown
      .slice()
      .sort((a, b) => progressOf(b.summary) - progressOf(a.summary) || byRecency(a, b))
  }
  return shown.slice().sort(byRecency)
}

/** Newest first, with "never touched" last rather than first.
 *
 * A null `lastActivity` compares as the empty string, which sorts *below*
 * every real timestamp — so a project nobody has opened lands at the bottom,
 * which is where a project with nothing in it belongs. That is the same
 * arrangement `landing.ts`'s `rollups` made and the one place this ordering is
 * unchanged.
 */
const byRecency = (a: ProjectListing, b: ProjectListing): number =>
  String(b.summary.lastActivity ?? '').localeCompare(String(a.summary.lastActivity ?? ''))
