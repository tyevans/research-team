import { describe, expect, it } from 'vitest'

import type { Catalog, CourseCandidate } from '@domain/knowledge/catalog.ts'

import type { CatalogQuery, CatalogSort } from './catalog-view.ts'
import { arrangeCatalog, isNarrowed, NO_QUERY } from './catalog-view.ts'

/** The catalog's arrangement, which is the whole of what jsdom can judge about
 *  this screen -- everything else on it is a computed style and belongs to
 *  `course-card-sizing.browser.test.tsx`.
 *
 * The cases below are chosen to *separate* the arrangement from the ones it
 * was written against, per CLAUDE.md's rule about a formula correct on every
 * case a test naturally reaches. Named where that is what a case is for.
 */

const aCandidate = (over: Partial<CourseCandidate> = {}): CourseCandidate => ({
  slug: 'roman-succession',
  title: 'The Roman Succession Crisis',
  category: 'antiquity',
  prominence: 0.5,
  size: 10,
  membershipHash: 'hash-1',
  anchors: [],
  art: { url: '/art/roman-succession.png', alt: 'A mosaic of an imperial court' },
  blurb: null,
  featuredRank: null,
  ...over,
})

const aCatalog = (over: Partial<Catalog> = {}): Catalog => ({
  sections: { hero: [], highlights: [], filed: [] },
  categories: new Map([['antiquity', 'Antiquity']]),
  unplaceableFeatured: [],
  unnamedCount: 0,
  orphanedCourses: [],
  derivedFrom: { entities: 100, relationships: 50 },
  ...over,
})

const ask = (over: Partial<CatalogQuery> = {}): CatalogQuery => ({ ...NO_QUERY, ...over })

const slugsOn = (catalog: Catalog, query: CatalogQuery, shelfKey: string) =>
  arrangeCatalog(catalog, query)
    .shelves.find((shelf) => shelf.key === shelfKey)
    ?.candidates.map((candidate) => candidate.slug)

describe('isNarrowed', () => {
  it('is false for the untouched query', () => {
    expect(isNarrowed(NO_QUERY)).toBe(false)
  })

  it('is true for a category with no search text', () => {
    // The case that distinguishes this predicate from `text !== ''`, which is
    // what it would have been if only the search box had been considered.
    // Picking a category is still a reader asking a question.
    expect(isNarrowed(ask({ category: 'antiquity' }))).toBe(true)
  })

  it('is false for whitespace alone', () => {
    // Distinguishes `text.trim() !== ''` from `text !== ''`. A reader who
    // pressed space in the search box has narrowed nothing, and answering them
    // with a flat, spotlight-less result page would be a whole front page
    // disappearing on one keystroke.
    expect(isNarrowed(ask({ text: '   ' }))).toBe(false)
  })
})

describe('arrangeCatalog, unnarrowed', () => {
  it('leads with the lowest-ranked featured candidate, not the most prominent', () => {
    // The distinguishing case, and the one the obvious implementation gets
    // wrong: the *less* prominent candidate is the one somebody featured
    // first. A spotlight chosen by prominence would pick the other one and
    // every ordinary catalog would look identical under both rules.
    const catalog = aCatalog({
      sections: {
        hero: [
          aCandidate({ slug: 'second', featuredRank: 2, prominence: 0.9 }),
          aCandidate({ slug: 'first', featuredRank: 1, prominence: 0.1 }),
        ],
        highlights: [],
        filed: [],
      },
    })

    expect(arrangeCatalog(catalog, NO_QUERY).spotlight?.slug).toBe('first')
  })

  it('falls back to the most prominent candidate when nothing is featured', () => {
    const catalog = aCatalog({
      sections: {
        hero: [],
        highlights: [
          aCandidate({ slug: 'quiet', prominence: 0.2 }),
          aCandidate({ slug: 'loud', prominence: 0.9 }),
        ],
        filed: [],
      },
    })

    expect(arrangeCatalog(catalog, NO_QUERY).spotlight?.slug).toBe('loud')
  })

  it('never repeats the spotlight on a shelf', () => {
    const catalog = aCatalog({
      sections: {
        hero: [
          aCandidate({ slug: 'first', featuredRank: 1 }),
          aCandidate({ slug: 'second', featuredRank: 2 }),
        ],
        highlights: [],
        filed: [],
      },
    })

    expect(slugsOn(catalog, NO_QUERY, 'hero')).toEqual(['second'])
  })

  it('drops a shelf that the spotlight emptied rather than showing an empty heading', () => {
    const catalog = aCatalog({
      sections: {
        hero: [aCandidate({ slug: 'only', featuredRank: 1 })],
        highlights: [],
        filed: [],
      },
    })

    expect(arrangeCatalog(catalog, NO_QUERY).shelves).toEqual([])
  })

  it.each<CatalogSort>(['prominence', 'size', 'title', 'fresh'])(
    'keeps the featured shelf in curated order under sort=%s',
    (sort) => {
      // Parametrised over every sort rather than over one representative
      // value, because the property under test is "the sort does not reach
      // this shelf" -- a test with one sort could not tell that rule from an
      // accident of which comparator happened to agree with the rank order.
      //
      // The candidates are arranged so that every comparator disagrees with
      // the rank *on the two that reach the shelf*, which is the part the
      // first draft of this test got wrong: it made rank 1 the outlier and
      // left ranks 2 and 3 in an order all four sorts already agreed with, so
      // it passed with `byRank` swapped for the reader's sort. Proved red on
      // 2026-08-27 by making that swap; it now fails on all four.
      //
      // Rank 1 is the spotlight. Ranks 2 and 3 are `zulu` then `alpha`, and
      // `alpha` is the more prominent, the larger, the earlier alphabetically
      // and the only one with copy -- so every sort would reverse them.
      const catalog = aCatalog({
        sections: {
          hero: [
            aCandidate({ slug: 'mid', title: 'Mid', featuredRank: 1, prominence: 0.5, size: 50 }),
            aCandidate({
              slug: 'zulu',
              title: 'Zulu',
              featuredRank: 2,
              prominence: 0.1,
              size: 1,
              blurb: null,
            }),
            aCandidate({
              slug: 'alpha',
              title: 'Alpha',
              featuredRank: 3,
              prominence: 0.9,
              size: 99,
              blurb: {
                text: 'x',
                membershipHash: 'hash-1',
                generatedAt: '2026-08-01T00:00:00Z',
              },
            }),
          ],
          highlights: [],
          filed: [],
        },
      })

      // The spotlight takes rank 1 (`mid`), so the shelf holds ranks 2 and 3
      // in that order under every sort.
      expect(slugsOn(catalog, ask({ sort }), 'hero')).toEqual(['zulu', 'alpha'])
    },
  )

  it('applies the sort to a shelf that is not curated', () => {
    // The other half of the case above: proves the sort is wired at all, so
    // "curated order survives" is a statement about the curated shelf rather
    // than about a control that does nothing anywhere.
    const catalog = aCatalog({
      sections: {
        hero: [],
        highlights: [
          aCandidate({ slug: 'zulu', title: 'Zulu' }),
          aCandidate({ slug: 'alpha', title: 'Alpha' }),
          aCandidate({ slug: 'mid', title: 'Mid' }),
        ],
        filed: [],
      },
    })

    // 'Alpha' is the spotlight under sort=title, leaving two.
    expect(slugsOn(catalog, ask({ sort: 'title' }), 'highlights')).toEqual(['mid', 'zulu'])
  })

  it('sorts by fresh copy, with uncopied candidates last', () => {
    // The two timestamps are chosen so that lexical and chronological order
    // agree -- which is the assumption `COMPARE.fresh` rests on and states.
    const written = (generatedAt: string) => ({
      text: 'copy',
      membershipHash: 'hash-1',
      generatedAt,
    })
    const catalog = aCatalog({
      sections: {
        hero: [],
        highlights: [
          aCandidate({ slug: 'old', blurb: written('2026-01-09T00:00:00Z') }),
          aCandidate({ slug: 'none', blurb: null }),
          aCandidate({ slug: 'new', blurb: written('2026-01-10T00:00:00Z') }),
        ],
        filed: [],
      },
    })

    // 'new' is the spotlight; 'none' must come after 'old' rather than before
    // it, which is the judgement `COMPARE.fresh` documents. A comparator
    // treating a missing date as zero would put it first.
    expect(slugsOn(catalog, ask({ sort: 'fresh' }), 'highlights')).toEqual(['old', 'none'])
  })

  it('lists every category from the map, including one whose candidates were all promoted', () => {
    // `sections.filed` is empty here and `categories` is not -- exactly the
    // state `Catalog.categories`' own docstring exists for. Deriving the
    // filter row from `filed` would silently drop the category.
    const catalog = aCatalog({
      categories: new Map([
        ['antiquity', 'Antiquity'],
        ['medieval', 'Medieval'],
      ]),
      sections: { hero: [], highlights: [aCandidate({ slug: 'a' })], filed: [] },
    })

    expect(arrangeCatalog(catalog, NO_QUERY).categories).toEqual([
      { key: 'antiquity', label: 'Antiquity' },
      { key: 'medieval', label: 'Medieval' },
    ])
  })

  it('counts every candidate across all three sections exactly once', () => {
    const catalog = aCatalog({
      sections: {
        hero: [aCandidate({ slug: 'a', featuredRank: 1 })],
        highlights: [aCandidate({ slug: 'b' })],
        filed: [{ key: 'antiquity', label: 'Antiquity', candidates: [aCandidate({ slug: 'c' })] }],
      },
    })

    const arranged = arrangeCatalog(catalog, NO_QUERY)
    expect(arranged.total).toBe(3)
    expect(arranged.matched).toBe(3)
  })
})

describe('arrangeCatalog, narrowed', () => {
  const searchable = aCatalog({
    sections: {
      hero: [],
      highlights: [
        aCandidate({ slug: 'succession', title: 'The Roman Succession Crisis' }),
        aCandidate({
          slug: 'aqueducts',
          title: 'Aqueducts',
          blurb: { text: 'How water reached the city.', membershipHash: 'hash-1', generatedAt: '' },
        }),
        aCandidate({
          slug: 'xindi',
          title: 'Xindi',
          anchors: [
            {
              entityId: 'e1',
              name: 'Delphine Coriolis',
              entityType: 'person',
              centrality: 1,
              temporal: null,
            },
          ],
        }),
      ],
      filed: [],
    },
  })

  it('draws no spotlight over a search result', () => {
    expect(arrangeCatalog(searchable, ask({ text: 'roman' })).spotlight).toBeNull()
  })

  it('answers a search on one flat shelf rather than the editorial sections', () => {
    const arranged = arrangeCatalog(searchable, ask({ text: 'roman' }))
    expect(arranged.shelves.map((shelf) => shelf.key)).toEqual(['results'])
    expect(arranged.matched).toBe(1)
    expect(arranged.total).toBe(3)
  })

  it('matches on the blurb, not only the title', () => {
    expect(slugsOn(searchable, ask({ text: 'water' }), 'results')).toEqual(['aqueducts'])
  })

  it('matches on an anchor name', () => {
    // The one search field that is not obvious and is the reason this search
    // is worth having: an area is often findable only by an entity somebody
    // remembers from it, and "Delphine Coriolis" appears in no title or blurb.
    expect(slugsOn(searchable, ask({ text: 'coriolis' }), 'results')).toEqual(['xindi'])
  })

  it('matches case-insensitively', () => {
    expect(slugsOn(searchable, ask({ text: 'ROMAN' }), 'results')).toEqual(['succession'])
  })

  it('returns no shelf at all when nothing matches', () => {
    const arranged = arrangeCatalog(searchable, ask({ text: 'nothing here' }))
    expect(arranged.shelves).toEqual([])
    expect(arranged.matched).toBe(0)
  })

  it('restricts to one category', () => {
    const catalog = aCatalog({
      categories: new Map([
        ['antiquity', 'Antiquity'],
        ['medieval', 'Medieval'],
      ]),
      sections: {
        hero: [],
        highlights: [
          aCandidate({ slug: 'rome', category: 'antiquity' }),
          aCandidate({ slug: 'charlemagne', category: 'medieval' }),
        ],
        filed: [],
      },
    })

    expect(slugsOn(catalog, ask({ category: 'medieval' }), 'results')).toEqual(['charlemagne'])
  })
})
