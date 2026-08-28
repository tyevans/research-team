import type { Catalog, CourseCandidate } from '@domain/knowledge/catalog.ts'

/** How the catalog's front page is arranged, as a fold over the fetched
 *  `Catalog` and the reader's own controls. No React, no fetching.
 *
 * It lives here rather than inside `CatalogPane` for the reason `stepsOf` does
 * in `curriculum.ts`: this is a join and a sort the server deliberately does
 * not make, and a lookup that can silently miss does not belong inside a
 * render. It is also the half of this screen that is worth testing in jsdom --
 * most of the rest of the catalog is a computed style, which jsdom cannot
 * judge at all.
 *
 * **Why the search is client-side.** `GET /catalog` already answers with every
 * candidate in the project, blurbs and anchors included; a candidate is a
 * cluster, and a project has tens of them rather than thousands. A server
 * round-trip per keystroke would buy nothing and cost a spinner over a list
 * that is already in memory. If a project ever holds enough candidates for
 * this to be the wrong call, the tell is `total` in `ArrangedCatalog` -- it is
 * the number this decision is sized against, which is why it is returned
 * rather than merely used.
 */

/** The orders a reader can ask for. `prominence` is the default and is the
 *  server's own ranking; the other three exist because each answers a question
 *  prominence cannot -- "what is the biggest area", "where is the one I can
 *  name", "what has just been written". */
export type CatalogSort = 'prominence' | 'size' | 'title' | 'fresh'

export interface CatalogQuery {
  /** Free text. Matched against title, slug, blurb, category label and anchor
   *  names -- anchors included because an area is often findable only by the
   *  entity a reader remembers from it, which is exactly what an anchor is. */
  readonly text: string
  readonly sort: CatalogSort
  /** A category key to restrict to, or `null` for every category. */
  readonly category: string | null
}

export const NO_QUERY: CatalogQuery = { text: '', sort: 'prominence', category: null }

/** Whether a query would narrow anything. The front page's shape depends on
 *  this and not on `text` alone: picking a category with an empty search box
 *  is still a reader who has asked a question, and answering it with the
 *  unfiltered three-section front page would ignore them. */
export const isNarrowed = (query: CatalogQuery): boolean =>
  query.text.trim() !== '' || query.category !== null

export interface CatalogShelf {
  readonly key: string
  readonly label: string
  readonly candidates: readonly CourseCandidate[]
  /** True for the curated shelf, whose order is `featuredRank` rather than the
   *  reader's chosen sort -- see `arrangeCatalog`. Rendered as a note beside
   *  the heading so that "the sort control did nothing here" is stated rather
   *  than discovered. */
  readonly curated: boolean
}

export interface ArrangedCatalog {
  /** The one candidate drawn large at the top, or `null` when there is nothing
   *  to draw or the reader has narrowed the page -- a spotlight over a search
   *  result is a second answer competing with the list. */
  readonly spotlight: CourseCandidate | null
  readonly shelves: readonly CatalogShelf[]
  /** Every category in the catalog, for the filter row. Taken from
   *  `Catalog.categories` rather than from `sections.filed`, because a
   *  category whose every candidate was promoted has no entry in the second --
   *  see that field's own docstring. */
  readonly categories: readonly { readonly key: string; readonly label: string }[]
  /** How many candidates the query matched, and how many exist. Equal when
   *  nothing is narrowed. */
  readonly matched: number
  readonly total: number
}

/** Every candidate the catalog holds, deduplicated by slug.
 *
 * The three sections partition the catalog server-side -- a promoted candidate
 * leaves its category -- so the dedupe is belt and braces rather than a fix for
 * an observed overlap. It is here because the failure it prevents is a React
 * key collision, which renders as one card silently missing rather than as an
 * error.
 */
const allCandidates = (catalog: Catalog): CourseCandidate[] => {
  const seen = new Map<string, CourseCandidate>()
  const take = (candidates: readonly CourseCandidate[]) => {
    for (const candidate of candidates) {
      if (!seen.has(candidate.slug)) seen.set(candidate.slug, candidate)
    }
  }
  take(catalog.sections.hero)
  take(catalog.sections.highlights)
  for (const category of catalog.sections.filed) take(category.candidates)
  return [...seen.values()]
}

const matches = (candidate: CourseCandidate, needle: string, categoryLabel: string): boolean => {
  if (needle === '') return true
  const haystack = [
    candidate.title,
    candidate.slug,
    categoryLabel,
    candidate.blurb?.text ?? '',
    ...candidate.anchors.map((anchor) => anchor.name),
  ]
  return haystack.some((field) => field.toLowerCase().includes(needle))
}

/** The comparators, one per sort.
 *
 * `fresh` puts a candidate with no blurb *last* rather than first, which is the
 * one of the four that is a judgement rather than an arithmetic fact: an absent
 * `generatedAt` is not "written at the beginning of time", it is "not written",
 * and a reader asking what was written most recently is not asking to be shown
 * the things nothing has written.
 *
 * `generatedAt` is compared as a string rather than parsed. It is an ISO-8601
 * instant from the server, and ISO-8601 in a fixed zone sorts lexically in the
 * same order it sorts chronologically -- `catalog-view.test.ts` pins that with
 * two timestamps whose lexical and chronological orders would disagree if the
 * field were ever anything else.
 */
const COMPARE: Record<CatalogSort, (a: CourseCandidate, b: CourseCandidate) => number> = {
  prominence: (a, b) => b.prominence - a.prominence,
  size: (a, b) => b.size - a.size,
  title: (a, b) => a.title.localeCompare(b.title),
  fresh: (a, b) => {
    const at = a.blurb?.generatedAt ?? null
    const bt = b.blurb?.generatedAt ?? null
    if (at === null && bt === null) return 0
    if (at === null) return 1
    if (bt === null) return -1
    return bt.localeCompare(at)
  },
}

/** Curated order: rank 1 first. Every candidate on the curated shelf has a rank
 *  by construction, and the `?? 0` is only there because the type permits
 *  `null`; a candidate reaching here without one sorts to the front, which is
 *  the harmless direction. */
const byRank = (a: CourseCandidate, b: CourseCandidate) =>
  (a.featuredRank ?? 0) - (b.featuredRank ?? 0)

/** Arrange the catalog for the front page.
 *
 * **The curated shelf keeps `featuredRank` order regardless of the sort.** That
 * is deliberate and it is the one place this function ignores the reader's
 * control. Featuring *is* an ordering -- it is the only ordering a person in
 * this system has authored, everything else being a number the server computed
 * -- and a sort control that scrambled it would discard the single piece of
 * human curation on the page every time somebody wanted the rest of it
 * alphabetised. The shelf carries `curated: true` so the surface can say so out
 * loud rather than leaving a reader to notice the control did nothing.
 *
 * The cost, stated because it is real: `prominence` and `title` therefore mean
 * "everywhere except the featured shelf", which is a rule a reader has to be
 * told. The alternative was a fifth sort value meaning "as curated", which
 * makes the curation destroyable by picking any of the other four -- a worse
 * trade, and silently so.
 */
export const arrangeCatalog = (catalog: Catalog, query: CatalogQuery): ArrangedCatalog => {
  const labelOf = (key: string) => catalog.categories.get(key) ?? key
  const needle = query.text.trim().toLowerCase()
  const everything = allCandidates(catalog)

  const kept = everything.filter(
    (candidate) =>
      (query.category === null || candidate.category === query.category) &&
      matches(candidate, needle, labelOf(candidate.category)),
  )
  const sorted = [...kept].sort(COMPARE[query.sort])

  const categories = [...catalog.categories.entries()]
    .map(([key, label]) => ({ key, label }))
    .sort((a, b) => a.label.localeCompare(b.label))

  const counts = { matched: kept.length, total: everything.length, categories }

  // Narrowed: one flat answer, in the reader's own order. The three-section
  // front page is an editorial arrangement, and an editorial arrangement of
  // somebody's search results is a way of hiding two thirds of them under
  // headings they did not ask about.
  if (isNarrowed(query)) {
    return {
      ...counts,
      spotlight: null,
      // No shelf at all when nothing matched, rather than a heading over an
      // empty row. The surface says "nothing matches" once, in its own words;
      // a "Results 0" heading beside that message is the same fact twice, and
      // the heading is the less useful of the two.
      shelves:
        sorted.length === 0
          ? []
          : [{ key: 'results', label: 'Results', candidates: sorted, curated: false }],
    }
  }

  // The spotlight is the first *curated* card when there is one, and the top
  // of the reader's own order otherwise. Falling back rather than leaving the
  // banner empty: a project nobody has curated is the ordinary state, and a
  // front page whose largest element only appears once somebody has pressed
  // Feature is a page that looks broken until it is used.
  const featured = catalog.sections.hero.filter((c) => c.featuredRank !== null).sort(byRank)
  const spotlight = featured[0] ?? sorted[0] ?? null

  const rest = (candidates: readonly CourseCandidate[]) =>
    candidates.filter((c) => c.slug !== spotlight?.slug)

  const shelves: CatalogShelf[] = []

  const heroRest = rest(catalog.sections.hero).sort(byRank)
  if (heroRest.length > 0) {
    shelves.push({ key: 'hero', label: 'Featured', candidates: heroRest, curated: true })
  }

  const highlights = rest(catalog.sections.highlights).sort(COMPARE[query.sort])
  if (highlights.length > 0) {
    shelves.push({ key: 'highlights', label: 'Highlights', candidates: highlights, curated: false })
  }

  for (const category of catalog.sections.filed) {
    const candidates = rest(category.candidates).sort(COMPARE[query.sort])
    if (candidates.length > 0) {
      shelves.push({ key: category.key, label: category.label, candidates, curated: false })
    }
  }

  return { ...counts, spotlight, shelves }
}
