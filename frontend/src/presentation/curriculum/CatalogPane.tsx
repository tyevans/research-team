import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import type { CourseCandidate } from '@domain/knowledge/catalog.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'
import { ErrorBox, Loading } from '../common/primitives.tsx'
import { CategoryPage } from './CategoryPage.tsx'
import { CourseCard } from './CourseCard.tsx'

/** The Curriculum tab's default reading: the front page a person browses,
 *  beside the two analytic readings (`area`, `path`) `CurriculumPane` already
 *  draws -- this does not replace either, see `routes.ts`'s `FACETS` comment.
 *
 * Its own component and its own fetch rather than a third `CurriculumPane`
 * reading: this consumes `CatalogRepository`, a different response shape
 * (`Catalog`, not `Curriculum`) cached under its own key, and folding it into
 * the existing pane would make one component poll two projections that
 * invalidate on different writes -- a feature/unfeature here has nothing to
 * say about the area map.
 */
export const CatalogPane = ({
  projectId,
  categoryKey,
  onCategory,
}: {
  projectId: ProjectId
  /** The category open on the category page, or `null` for the front page.
   *  Owned by the route (`#/p/<id>/catalog/<key>`) for the reason every other
   *  selection here is: a category is worth sending to somebody. */
  categoryKey: string | null
  onCategory: (key: string | null) => void
}) => {
  const { catalog } = useContainer()
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: queryKeys.catalog(projectId),
    queryFn: () => catalog.catalog(projectId),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.catalog(projectId) })

  const feature = useMutation({
    mutationFn: ({ slug, rank }: { slug: string; rank: number }) =>
      catalog.feature(projectId, slug, rank),
    onSuccess: () => void invalidate(),
  })

  const unfeature = useMutation({
    mutationFn: (slug: string) => catalog.unfeature(projectId, slug),
    onSuccess: () => void invalidate(),
  })

  if (query.isPending) return <Loading what="the catalog" />
  if (query.isError) {
    return (
      <ErrorBox
        heading="The catalog could not be built."
        message={query.error instanceof Error ? query.error.message : 'Unknown error.'}
        onRetry={() => void query.refetch()}
      />
    )
  }

  const data = query.data

  // Featuring has no reorder control on this page yet, so a fresh feature
  // always lands after whatever the front page already carries. A placeholder
  // ordering, stated as one rather than left implicit: a drag-to-reorder
  // affordance is later work, not a decision made here.
  const onFeature = (candidate: CourseCandidate) =>
    feature.mutate({ slug: candidate.slug, rank: data.sections.hero.length + 1 })
  const onUnfeature = (slug: string) => unfeature.mutate(slug)

  if (categoryKey !== null) {
    // A category the catalog once held but has since emptied (every member
    // promoted to hero or highlights) has no entry in `sections.filed` -- only
    // in `categories`, which is why that map exists at all. Falling back to a
    // synthesised empty category rather than treating a missing `find` as "no
    // such category" keeps `#/p/<id>/catalog/<key>` open on a real label
    // instead of bouncing a reader who followed a link that was correct when
    // it was written.
    const category = data.sections.filed.find((c) => c.key === categoryKey) ?? {
      key: categoryKey,
      label: data.categories.get(categoryKey) ?? categoryKey,
      candidates: [],
    }
    return (
      <CategoryPage
        category={category}
        // No standalone candidate-detail view exists yet -- opening a card
        // here re-opens its own category, which is a no-op the reader already
        // sees. Deliberately left as the honest placeholder rather than wired
        // to nothing: the button still needs a handler to satisfy `CourseCard`.
        onOpen={() => onCategory(categoryKey)}
        onBack={() => onCategory(null)}
        onFeature={onFeature}
        onUnfeature={onUnfeature}
      />
    )
  }

  return (
    <div className="flex min-h-0 flex-col gap-4 overflow-y-auto p-3">
      {data.unplaceableFeatured.length > 0 && (
        // Curation stranded by re-clustering, reported rather than dropped --
        // see `Catalog.unplaceableFeatured`'s own docstring. Rendered as
        // visible text naming the slugs: the whole reason the server keeps
        // this list rather than silently dropping the feature is that a
        // curator has to be able to see and act on it, which a console
        // warning or a tooltip would not give them.
        <div
          role="status"
          className="border-0 border-l-2 border-solid border-accent bg-bg-raise px-3 py-2 text-sm text-fg"
        >
          <p className="font-semibold">
            {data.unplaceableFeatured.length}{' '}
            {data.unplaceableFeatured.length === 1
              ? 'featured course has'
              : 'featured courses have'}{' '}
            no area to show anymore:
          </p>
          <p className="text-fg-muted">{data.unplaceableFeatured.join(', ')}</p>
        </div>
      )}

      <CandidateSection
        heading="Hero"
        candidates={data.sections.hero}
        size="hero"
        onOpenCategory={onCategory}
        onFeature={onFeature}
        onUnfeature={onUnfeature}
      />
      <CandidateSection
        heading="Highlights"
        candidates={data.sections.highlights}
        size="highlight"
        onOpenCategory={onCategory}
        onFeature={onFeature}
        onUnfeature={onUnfeature}
      />

      <section className="flex flex-col gap-2">
        <h2 className="font-semibold tracking-wide text-sm text-fg uppercase">Filed</h2>
        <div className="flex flex-wrap gap-2">
          {data.sections.filed.map((category) => (
            <Button key={category.key} small onClick={() => onCategory(category.key)}>
              {category.label} ({category.candidates.length})
            </Button>
          ))}
        </div>
      </section>
    </div>
  )
}

/** One row of cards, each paired with the feature control its current state
 *  calls for. Shared by Hero and Highlights rather than written twice: the
 *  two sections differ only in `size` and which candidates they hold.
 */
const CandidateSection = ({
  heading,
  candidates,
  size,
  onOpenCategory,
  onFeature,
  onUnfeature,
}: {
  heading: string
  candidates: readonly CourseCandidate[]
  size: 'hero' | 'highlight'
  onOpenCategory: (key: string) => void
  onFeature: (candidate: CourseCandidate) => void
  onUnfeature: (slug: string) => void
}) => (
  <section className="flex flex-col gap-2">
    <h2 className="font-semibold tracking-wide text-sm text-fg uppercase">{heading}</h2>
    {candidates.length === 0 ? (
      <p className="text-fg-muted text-sm">Nothing here yet.</p>
    ) : (
      <div className="flex flex-wrap gap-3">
        {candidates.map((candidate) => (
          <div key={candidate.slug} className="flex flex-col items-stretch gap-1">
            {/* Ignores the slug `CourseCard` hands back: the candidate is
                already in this closure, and its `category` is what "opening"
                it means here until a standalone detail view exists. */}
            <CourseCard
              candidate={candidate}
              size={size}
              onOpen={() => onOpenCategory(candidate.category)}
            />
            {candidate.featuredRank === null ? (
              <Button small onClick={() => onFeature(candidate)}>
                Feature
              </Button>
            ) : (
              <Button small tone="quiet" onClick={() => onUnfeature(candidate.slug)}>
                Unfeature
              </Button>
            )}
          </div>
        ))}
      </div>
    )}
  </section>
)
