import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { useEffect, useRef } from 'react'

import { useContainer } from '@app/container-context.tsx'
import type { BlurbSweepProgress } from '@application/ports/repositories.ts'
import { queryKeys } from '@application/queries/keys.ts'
import type { CourseCandidate, OrphanedCourse } from '@domain/knowledge/catalog.ts'
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
  onCourse,
}: {
  projectId: ProjectId
  /** The category open on the category page, or `null` for the front page.
   *  Owned by the route (`#/p/<id>/catalog/<key>`) for the reason every other
   *  selection here is: a category is worth sending to somebody. */
  categoryKey: string | null
  onCategory: (key: string | null) => void
  /** Opens a candidate's own course page. Replaces the placeholder that used
   *  to send a card's own click back into its category -- see this file's
   *  git history for the reasoning that placeholder carried while no
   *  standalone course view existed. */
  onCourse: (slug: string) => void
}) => {
  const { catalog, courses } = useContainer()
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: queryKeys.catalog(projectId),
    queryFn: () => catalog.catalog(projectId),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.catalog(projectId) })

  // Its own key and its own poll, matching `RunPanel`'s reasoning
  // (`queryKeys.blurbSweep`'s own comment): polling only while a sweep is
  // running, and on `catalog`'s key would refetch the whole front page every
  // two seconds instead of just the four counts a sweep reports.
  const sweep = useQuery({
    queryKey: queryKeys.blurbSweep(projectId),
    queryFn: () => courses.fetchBlurbSweep(projectId),
    refetchInterval: (q) => (q.state.data?.running ? 2_000 : false),
  })

  const startSweep = useMutation({
    mutationFn: () => courses.startBlurbSweep(projectId),
    onSuccess: (started) => queryClient.setQueryData(queryKeys.blurbSweep(projectId), started),
  })

  // A poll transitioning `running: true` -> `false` is the one moment fresh
  // blurbs exist that `catalog`'s own cache does not know about yet -- a ref
  // rather than deriving it from the query's own status, because `useQuery`
  // has no "this poll just stopped" event, only the value each poll reads.
  const wasRunning = useRef(false)
  const running = sweep.data?.running ?? false
  useEffect(() => {
    if (wasRunning.current && !running) void invalidate()
    wasRunning.current = running
  }, [running]) // eslint-disable-line react-hooks/exhaustive-deps -- `invalidate` is a fresh closure every render; only `running` should re-run this.

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
        onOpen={onCourse}
        onBack={() => onCategory(null)}
        onFeature={onFeature}
        onUnfeature={onUnfeature}
      />
    )
  }

  return (
    <div className="flex min-h-0 flex-col gap-4 overflow-y-auto p-3">
      <BlurbSweepControl
        progress={sweep.data ?? null}
        starting={startSweep.isPending}
        onRun={() => startSweep.mutate()}
      />

      {data.orphanedCourses.length > 0 && <OrphanedCoursesStrip courses={data.orphanedCourses} />}

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
        onOpen={onCourse}
        onFeature={onFeature}
        onUnfeature={onUnfeature}
      />
      <CandidateSection
        heading="Highlights"
        candidates={data.sections.highlights}
        size="highlight"
        onOpen={onCourse}
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
  onOpen,
  onFeature,
  onUnfeature,
}: {
  heading: string
  candidates: readonly CourseCandidate[]
  size: 'hero' | 'highlight'
  onOpen: (slug: string) => void
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
            <CourseCard candidate={candidate} size={size} onOpen={onOpen} />
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

/** "Write the missing copy" and its progress line, over `catalog/blurbs`.
 *
 * Deliberately the same shape as `DiscoverySweep` (`presentation/research/`):
 * a button that starts a background sweep, a progress line polling the same
 * path, and an error state distinguished from an ordinary slow run. The one
 * difference from that sweep is where the counts come from -- discovery
 * counts a client-side loop over one document at a time, this counts a
 * server-side background task, so `progress` is `null` only before the first
 * poll has answered rather than for a work list not yet loaded.
 */
const BlurbSweepControl = ({
  progress,
  starting,
  onRun,
}: {
  progress: BlurbSweepProgress | null
  starting: boolean
  onRun: () => void
}) => {
  const running = starting || (progress?.running ?? false)
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-bg-panel p-3">
      <p className="m-0 min-w-0 flex-1 text-xs text-fg-dim">
        Write catalog copy for every candidate whose blurb is missing or out of date.
      </p>
      <Button small onClick={onRun} disabled={running}>
        {running && progress !== null
          ? `Writing ${progress.done} of ${progress.total}`
          : running
            ? 'Writing…'
            : 'Write the missing copy'}
      </Button>
      {progress !== null && !running && (
        // `error` present is the one case that must not read as an ordinary
        // finish -- see `BlurbSweepProgress.error`'s own docstring: it is set
        // only when the run itself raised, which `failed` alone does not
        // report. Checked first, so a died sweep can never also print the
        // done/total/failed line as if it had settled normally.
        <p
          className={clsx(
            'm-0 w-full text-xs',
            progress.error !== null ? 'text-k-failure' : 'text-fg-dim',
          )}
        >
          {progress.error !== null
            ? `The sweep failed: ${progress.error}`
            : `${progress.done} of ${progress.total} written${
                progress.failed > 0 ? `, ${progress.failed} failed` : ''
              }.`}
        </p>
      )}
    </div>
  )
}

/** Realized courses re-clustering stranded -- see `OrphanedCourse`'s own
 *  docstring for why this strip is their only surface: the detail route
 *  looks up a slug in the *current* catalog and 404s for one of these.
 */
const OrphanedCoursesStrip = ({ courses }: { courses: readonly OrphanedCourse[] }) => (
  <div
    role="status"
    className="border-0 border-l-2 border-solid border-accent bg-bg-raise px-3 py-2 text-sm text-fg"
  >
    <p className="font-semibold">
      {courses.length} realized {courses.length === 1 ? 'course has' : 'courses have'} no cluster to
      show anymore:
    </p>
    <ul className="text-fg-muted m-0 list-none p-0">
      {courses.map((course) => (
        <li key={course.slug}>
          {course.title} ({course.slug}) -- realized{' '}
          {new Date(course.realizedAt).toLocaleDateString()}
        </li>
      ))}
    </ul>
  </div>
)
