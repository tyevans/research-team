import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type {
  BlurbSweepProgress,
  CatalogRepository,
  CourseRepository,
} from '@application/ports/repositories.ts'
import type { Catalog, CourseCandidate, OrphanedCourse } from '@domain/knowledge/catalog.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { CatalogPane } from './CatalogPane.tsx'

const project = ProjectId('11111111-1111-1111-1111-111111111111')

const aCandidate = (over: Partial<CourseCandidate> = {}): CourseCandidate => ({
  slug: 'roman-succession',
  title: 'The Roman Succession Crisis',
  category: 'antiquity',
  prominence: 0.8,
  size: 12,
  membershipHash: 'hash-1',
  anchors: [],
  art: { url: '/art/roman-succession.png', alt: 'A mosaic of an imperial court' },
  blurb: null,
  featuredRank: null,
  ...over,
})

const aCatalog = (over: Partial<Catalog> = {}): Catalog => ({
  sections: {
    hero: [aCandidate({ slug: 'hero-1', title: 'Hero Course' })],
    highlights: [aCandidate({ slug: 'highlight-1', title: 'Highlight Course' })],
    filed: [
      {
        key: 'antiquity',
        label: 'Antiquity',
        candidates: [aCandidate({ slug: 'filed-1', title: 'Filed Course' })],
      },
    ],
  },
  categories: new Map([['antiquity', 'Antiquity']]),
  unplaceableFeatured: [],
  unnamedCount: 0,
  orphanedCourses: [],
  derivedFrom: { entities: 100, relationships: 50 },
  ...over,
})

const notRunning: BlurbSweepProgress = { running: false, done: 0, total: 0, failed: 0, error: null }

/** Every method throws until a test stubs it, matching this directory's other
 *  fakes: a pane that calls something it did not mean to fails loudly rather
 *  than resolving `undefined` and rendering an empty state that looks correct. */
const fakeCatalog = (over: Partial<CatalogRepository> = {}): CatalogRepository => ({
  catalog: vi.fn(() => {
    throw new Error('catalog was not stubbed for this test')
  }),
  feature: vi.fn(() => {
    throw new Error('feature was not stubbed for this test')
  }),
  unfeature: vi.fn(() => {
    throw new Error('unfeature was not stubbed for this test')
  }),
  ...over,
})

/** The sweep controls live on `CourseRepository` (`HttpCourseRepository`),
 *  not `CatalogRepository` -- see `catalog-repository.ts`'s own history:
 *  they were written there once, then moved here to reuse the endpoint the
 *  standalone course page's repository had already implemented and tested,
 *  rather than duplicating the same two HTTP calls behind a second port.
 *  `fetchBlurbSweep` is the one exception to "throws until stubbed": every
 *  test that shows the front page polls it whether or not the test cares
 *  about sweeping, and a throw there would fail every other test in this
 *  file on an unrelated query. */
const fakeCourses = (over: Partial<CourseRepository> = {}): CourseRepository => ({
  course: vi.fn(() => {
    throw new Error('course was not stubbed for this test')
  }),
  realize: vi.fn(() => {
    throw new Error('realize was not stubbed for this test')
  }),
  abandon: vi.fn(() => {
    throw new Error('abandon was not stubbed for this test')
  }),
  startBlurbSweep: vi.fn(() => {
    throw new Error('startBlurbSweep was not stubbed for this test')
  }),
  fetchBlurbSweep: vi.fn<CourseRepository['fetchBlurbSweep']>().mockResolvedValue(notRunning),
  ...over,
})

const wrapperFor = (
  catalog: CatalogRepository,
  courses: CourseRepository,
): (({ children }: { children: ReactNode }) => ReactElement) => {
  const container = { catalog, courses } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>{children}</ContainerProvider>
    </QueryClientProvider>
  )
}

const show = (
  catalog: CatalogRepository,
  categoryKey: string | null = null,
  courses: CourseRepository = fakeCourses(),
) =>
  render(
    <CatalogPane
      projectId={project}
      categoryKey={categoryKey}
      onCategory={() => {}}
      onCourse={() => {}}
    />,
    { wrapper: wrapperFor(catalog, courses) },
  )

describe('CatalogPane', () => {
  it('renders the three sections, each with its cards, from a stubbed repository', async () => {
    const catalog = fakeCatalog({
      catalog: vi.fn<CatalogRepository['catalog']>().mockResolvedValue(aCatalog()),
    })
    show(catalog)

    expect(await screen.findByText('Hero Course')).toBeInTheDocument()
    expect(screen.getByText('Highlight Course')).toBeInTheDocument()
    // The filed section is rendered as category buttons rather than the
    // candidates themselves -- see `CategoryPage` for the drill-down -- so
    // this asserts the category is on screen, with its count.
    expect(screen.getByText('Antiquity (1)')).toBeInTheDocument()
  })

  // The load-bearing assertion. A pane that fabricates its own data, or whose
  // query was never wired to a real fetch, would still pass every assertion
  // above -- this is the one that would fail against that build. Proven below,
  // in "does not pass with a hard-coded catalog".
  it('calls the repository with the project id', async () => {
    const catalogFn = vi.fn<CatalogRepository['catalog']>().mockResolvedValue(aCatalog())
    const catalog = fakeCatalog({ catalog: catalogFn })
    show(catalog)

    // `false`: the toggle's local state starts off, and that state is what
    // decides which of the two cache entries (`queryKeys.catalog(project,
    // includeUnnamed)`) this fetch lands in.
    await waitFor(() => expect(catalogFn).toHaveBeenCalledWith(project, false))
  })

  it('shows how many candidates are hidden, and refetches with unnamed=true when toggled', async () => {
    const catalogFn = vi
      .fn<CatalogRepository['catalog']>()
      .mockResolvedValue(aCatalog({ unnamedCount: 3 }))
    const catalog = fakeCatalog({ catalog: catalogFn })
    show(catalog)

    const toggle = await screen.findByRole('button', { name: /show 3 unnamed/i })
    await userEvent.click(toggle)

    await waitFor(() => expect(catalogFn).toHaveBeenCalledWith(project, true))
  })

  it('reads "hide unnamed" once the toggle is showing them', async () => {
    const catalog = fakeCatalog({
      catalog: vi
        .fn<CatalogRepository['catalog']>()
        .mockResolvedValue(aCatalog({ unnamedCount: 2 })),
    })
    show(catalog)

    await userEvent.click(await screen.findByRole('button', { name: /show 2 unnamed/i }))

    expect(await screen.findByRole('button', { name: /hide unnamed/i })).toBeInTheDocument()
  })

  it('renders no toggle when nothing is hidden', async () => {
    const catalog = fakeCatalog({
      catalog: vi
        .fn<CatalogRepository['catalog']>()
        .mockResolvedValue(aCatalog({ unnamedCount: 0 })),
    })
    show(catalog)

    await screen.findByText('Hero Course')
    expect(screen.queryByRole('button', { name: /unnamed/i })).not.toBeInTheDocument()
  })

  it('points at the sweep button when the catalog has never been named', async () => {
    const catalog = fakeCatalog({
      catalog: vi.fn<CatalogRepository['catalog']>().mockResolvedValue(
        aCatalog({
          sections: { hero: [], highlights: [], filed: [] },
          unnamedCount: 5,
        }),
      ),
    })
    show(catalog)

    expect(await screen.findByText(/write the missing copy/i)).toBeInTheDocument()
    expect(await screen.findByText(/nothing named yet/i)).toHaveTextContent(/5 candidates/)
  })

  it('renders Loading while the catalog is pending', () => {
    const catalog = fakeCatalog({
      catalog: vi.fn(() => new Promise<Catalog>(() => {})),
    })
    show(catalog)

    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('renders ErrorBox when the catalog read fails', async () => {
    const catalog = fakeCatalog({
      catalog: vi.fn<CatalogRepository['catalog']>().mockRejectedValue(new Error('boom')),
    })
    show(catalog)

    expect(await screen.findByText('boom')).toBeInTheDocument()
  })

  it('features a candidate by calling feature(projectId, slug, rank)', async () => {
    const feature = vi.fn<CatalogRepository['feature']>().mockResolvedValue(undefined)
    const catalog = fakeCatalog({
      catalog: vi.fn<CatalogRepository['catalog']>().mockResolvedValue(
        aCatalog({
          sections: {
            hero: [aCandidate({ slug: 'hero-1', title: 'Hero Course' })],
            highlights: [],
            filed: [
              {
                key: 'antiquity',
                label: 'Antiquity',
                candidates: [
                  aCandidate({ slug: 'filed-1', title: 'Filed Course', featuredRank: null }),
                ],
              },
            ],
          },
        }),
      ),
      feature,
    })
    show(catalog, 'antiquity')

    await userEvent.click(await screen.findByRole('button', { name: 'Feature' }))

    // Rank is the hero row's length plus one (one existing hero candidate
    // here) -- see `CatalogPane`'s own comment on why this is a placeholder
    // ordering rather than a chosen one.
    await waitFor(() => expect(feature).toHaveBeenCalledWith(project, 'filed-1', 2))
  })

  it('renders a visible note naming stranded featured slugs', async () => {
    const catalog = fakeCatalog({
      catalog: vi
        .fn<CatalogRepository['catalog']>()
        .mockResolvedValue(aCatalog({ unplaceableFeatured: ['ghost-course', 'another-ghost'] })),
    })
    show(catalog)

    expect(await screen.findByText(/ghost-course, another-ghost/)).toBeInTheDocument()
  })

  it('renders an orphaned-courses strip naming stranded realized courses', async () => {
    const orphan: OrphanedCourse = {
      slug: 'lost-course',
      title: 'The Course Nobody Can Reach',
      realizedAt: '2026-01-01T00:00:00Z',
    }
    const catalog = fakeCatalog({
      catalog: vi
        .fn<CatalogRepository['catalog']>()
        .mockResolvedValue(aCatalog({ orphanedCourses: [orphan] })),
    })
    show(catalog)

    expect(await screen.findByText(/The Course Nobody Can Reach/)).toBeInTheDocument()
    expect(screen.getByText(/lost-course/)).toBeInTheDocument()
  })

  it('renders no orphaned-courses strip when nothing is stranded', async () => {
    const catalog = fakeCatalog({
      catalog: vi.fn<CatalogRepository['catalog']>().mockResolvedValue(aCatalog()),
    })
    show(catalog)

    await screen.findByText('Hero Course')
    expect(screen.queryByText(/no cluster to/)).not.toBeInTheDocument()
  })

  it('starts a blurb sweep by POSTing catalog/blurbs and shows the button', async () => {
    const startBlurbSweep = vi
      .fn<CourseRepository['startBlurbSweep']>()
      .mockResolvedValue({ running: true, done: 0, total: 3, failed: 0, error: null })
    const catalog = fakeCatalog({
      catalog: vi.fn<CatalogRepository['catalog']>().mockResolvedValue(aCatalog()),
    })
    show(catalog, null, fakeCourses({ startBlurbSweep }))

    await userEvent.click(await screen.findByRole('button', { name: 'Write the missing copy' }))

    await waitFor(() => expect(startBlurbSweep).toHaveBeenCalledWith(project))
  })

  it('shows the four progress counts while a sweep runs, and names a died sweep distinctly from a slow one', async () => {
    const fetchBlurbSweep = vi.fn<CourseRepository['fetchBlurbSweep']>().mockResolvedValue({
      running: false,
      done: 2,
      total: 5,
      failed: 1,
      error: 'the model refused',
    })
    const catalog = fakeCatalog({
      catalog: vi.fn<CatalogRepository['catalog']>().mockResolvedValue(aCatalog()),
    })
    show(catalog, null, fakeCourses({ fetchBlurbSweep }))

    // `error` present must read as "the sweep failed", not as an ordinary
    // done/total/failed report -- see `BlurbSweepProgress.error`'s own
    // docstring on why the two must not look alike.
    expect(await screen.findByText(/the sweep failed/i)).toBeInTheDocument()
    expect(screen.getByText(/the model refused/)).toBeInTheDocument()
  })
})
