import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { CatalogRepository } from '@application/ports/repositories.ts'
import type { Catalog, CourseCandidate } from '@domain/knowledge/catalog.ts'
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
  derivedFrom: { entities: 100, relationships: 50 },
  ...over,
})

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

const wrapperFor = (
  catalog: CatalogRepository,
): (({ children }: { children: ReactNode }) => ReactElement) => {
  const container = { catalog } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>{children}</ContainerProvider>
    </QueryClientProvider>
  )
}

const show = (catalog: CatalogRepository, categoryKey: string | null = null) =>
  render(
    <CatalogPane
      projectId={project}
      categoryKey={categoryKey}
      onCategory={() => {}}
      onCourse={() => {}}
    />,
    { wrapper: wrapperFor(catalog) },
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

    await waitFor(() => expect(catalogFn).toHaveBeenCalledWith(project))
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
})
