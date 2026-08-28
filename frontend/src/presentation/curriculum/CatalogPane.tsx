import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { useEffect, useMemo, useRef, useState } from 'react'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import type { CourseCandidate, OrphanedCourse } from '@domain/knowledge/catalog.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'
import { ErrorBox, Loading } from '../common/primitives.tsx'
import type { CatalogQuery, CatalogShelf } from './catalog-view.ts'
import { arrangeCatalog, NO_QUERY } from './catalog-view.ts'
import { CatalogSpotlight } from './CatalogSpotlight.tsx'
import { CatalogToolbar } from './CatalogToolbar.tsx'
import { CatalogTools, SweepBanner } from './CatalogTools.tsx'
import { CategoryPage } from './CategoryPage.tsx'
import { CourseCard } from './CourseCard.tsx'

/** The Curriculum tab's default reading: the front page a person browses,
 *  beside the two analytic readings (`area`, `path`) `CurriculumPane` already
 *  draws -- this does not replace either, see `routes.ts`'s `FACETS` comment.
 *
 * **What this page is for, since the redesign turned on the answer.** A
 * project's graph is clustered into learning areas; each cluster is a *course
 * candidate*. Two people read this page. One is browsing -- "what could this
 * research teach?" -- and wants an entry point, a way to search, and enough of
 * each candidate to decide whether to open it. The other is curating -- "these
 * three lead" -- and wants featuring to be one gesture per card. Neither was
 * served well: the page opened with two sweep-control boxes, drew three
 * sections of near-identical cards in one server-chosen order, offered no
 * search at all, and put curation in a `Feature`/`Unfeature` button parked
 * *under* each card.
 *
 * The measurable version of "offered no search": `prominence`, `size`,
 * `anchors` and `blurb.generatedAt` are on the wire for every candidate on
 * every request, and this page rendered none of the four.
 *
 * The shape now, top to bottom: a running-sweep line only while one runs; the
 * stranded-curation notices, which are the only things here that are somebody's
 * problem right now; search/sort/filter; one spotlight; shelves; and the sweeps
 * at the foot. `arrangeCatalog` in `catalog-view.ts` decides everything about
 * the middle of that list, and is where to look before this file.
 *
 * Its own component and its own fetch rather than a third `CurriculumPane`
 * reading: this consumes `CatalogRepository`, a different response shape
 * (`Catalog`, not `Curriculum`) cached under its own key, and folding it into
 * the existing pane would make one component poll two projections that
 * invalidate on different writes -- a feature/unfeature here has nothing to say
 * about the area map.
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
   *  selection here is: a category is worth sending to somebody.
   *
   *  The front page no longer *navigates* here -- its category filter narrows
   *  in place, which is what a browsing surface should do with a filter. The
   *  route stays because links to it were correct when they were written and
   *  the page it opens is still the right page for one. */
  categoryKey: string | null
  onCategory: (key: string | null) => void
  /** Opens a candidate's own course page. Replaces the placeholder that used
   *  to send a card's own click back into its category -- see this file's git
   *  history for the reasoning that placeholder carried while no standalone
   *  course view existed. */
  onCourse: (slug: string) => void
}) => {
  const { catalog, courses } = useContainer()
  const queryClient = useQueryClient()

  // Local, not persisted: the brief's own call -- a reader who flips this on to
  // check something is not expected to have it remembered next visit, and there
  // is nowhere on this pane that currently persists a view preference.
  const [showUnnamed, setShowUnnamed] = useState(false)

  // Same reasoning, one level up: search text, sort and category filter are a
  // question a reader is asking *now*. Persisting a sort is how somebody
  // returns to a catalog that is alphabetical for no reason they remember.
  const [query, setQuery] = useState<CatalogQuery>(NO_QUERY)

  const result = useQuery({
    queryKey: queryKeys.catalog(projectId, showUnnamed),
    queryFn: () => catalog.catalog(projectId, showUnnamed),
  })

  // Invalidates both cache entries (the key's `project` prefix matches either
  // `includeUnnamed` value) -- a feature/unfeature changes what both the shown
  // and hidden views would answer, not just the one currently on screen.
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['catalog', projectId] })

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

  // Its own key and its own poll, matching `sweep` above for the same reason:
  // an art sweep reports four unrelated counts, and sharing `catalog`'s key
  // would refetch the whole front page every two seconds instead of just those.
  const artSweep = useQuery({
    queryKey: queryKeys.artSweep(projectId),
    queryFn: () => courses.fetchArtSweep(projectId),
    refetchInterval: (q) => (q.state.data?.running ? 2_000 : false),
  })

  const startArtSweep = useMutation({
    mutationFn: (force: boolean) =>
      force ? courses.startArtSweep(projectId, { force: true }) : courses.startArtSweep(projectId),
    onSuccess: (started) => queryClient.setQueryData(queryKeys.artSweep(projectId), started),
  })

  // A poll transitioning `running: true` -> `false` is the one moment fresh
  // blurbs exist that `catalog`'s own cache does not know about yet -- a ref
  // rather than deriving it from the query's own status, because `useQuery` has
  // no "this poll just stopped" event, only the value each poll reads.
  const wasRunning = useRef(false)
  const running = sweep.data?.running ?? false
  useEffect(() => {
    if (wasRunning.current && !running) void invalidate()
    wasRunning.current = running
  }, [running]) // eslint-disable-line react-hooks/exhaustive-deps -- `invalidate` is a fresh closure every render; only `running` should re-run this.

  // Same reasoning as `wasRunning` above, for the art sweep's own poll: a
  // finished run is the one moment fresh `art.url`s exist that `catalog`'s
  // cache does not know about yet.
  const artWasRunning = useRef(false)
  const artRunning = artSweep.data?.running ?? false
  useEffect(() => {
    if (artWasRunning.current && !artRunning) void invalidate()
    artWasRunning.current = artRunning
  }, [artRunning]) // eslint-disable-line react-hooks/exhaustive-deps -- `invalidate` is a fresh closure every render; only `artRunning` should re-run this.

  const feature = useMutation({
    mutationFn: ({ slug, rank }: { slug: string; rank: number }) =>
      catalog.feature(projectId, slug, rank),
    onSuccess: () => void invalidate(),
  })

  const unfeature = useMutation({
    mutationFn: (slug: string) => catalog.unfeature(projectId, slug),
    onSuccess: () => void invalidate(),
  })

  const data = result.data ?? null

  // Memoised on the two things it folds. Not for speed -- the list is tens of
  // items -- but so the arrangement is one value per (catalog, query) pair
  // rather than a new array identity on every keystroke's re-render, which is
  // what would make every card in every shelf a new element to diff.
  const arranged = useMemo(
    () => (data === null ? null : arrangeCatalog(data, query)),
    [data, query],
  )

  if (result.isPending) return <Loading what="the catalog" />
  if (result.isError) {
    return (
      <ErrorBox
        heading="The catalog could not be built."
        message={result.error instanceof Error ? result.error.message : 'Unknown error.'}
        onRetry={() => void result.refetch()}
      />
    )
  }
  if (data === null || arranged === null) return <Loading what="the catalog" />

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
    // instead of bouncing a reader who followed a link that was correct when it
    // was written.
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

  // A cluster with no cached title falls back to `LearningArea.display_name()`
  // -- its single most central *entity*, e.g. "Xindi" -- which reads as an
  // entity name rather than a course, so the server hides it unless asked.
  // Every seeded-but-never-swept project lands here on its very first visit,
  // and a blank front page with no explanation reads as broken rather than as
  // "nothing has been named yet".
  const isEmpty = arranged.total === 0

  return (
    <div className="flex min-h-0 flex-col gap-4 overflow-y-auto p-3">
      <SweepBanner blurb={sweep.data ?? null} art={artSweep.data ?? null} />

      {data.orphanedCourses.length > 0 && <OrphanedCoursesStrip courses={data.orphanedCourses} />}

      {data.unplaceableFeatured.length > 0 && (
        // Curation stranded by re-clustering, reported rather than dropped --
        // see `Catalog.unplaceableFeatured`'s own docstring. Rendered as visible
        // text naming the slugs: the whole reason the server keeps this list
        // rather than silently dropping the feature is that a curator has to be
        // able to see and act on it, which a console warning or a tooltip would
        // not give them.
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
          <p className="text-fg-dim">{data.unplaceableFeatured.join(', ')}</p>
        </div>
      )}

      {!isEmpty && (
        <CatalogToolbar
          query={query}
          onQuery={setQuery}
          categories={arranged.categories}
          matched={arranged.matched}
          total={arranged.total}
        />
      )}

      {isEmpty && (
        // Points at the one action that gets this project out of the empty
        // state -- a message with nothing to do about it is worse than none,
        // and `unnamedCount` is what tells a reader whether the sweep has work
        // waiting (a positive count) or the graph itself is empty (zero,
        // `CatalogService.build`'s own default).
        <p role="status" className="text-sm text-fg-dim">
          {data.unnamedCount > 0
            ? `Nothing named yet. ${data.unnamedCount} candidate${
                data.unnamedCount === 1 ? '' : 's'
              } ${data.unnamedCount === 1 ? 'is' : 'are'} waiting on the sweep below, or show them unnamed.`
            : 'Nothing here yet.'}
        </p>
      )}

      {arranged.spotlight !== null && (
        <CatalogSpotlight
          candidate={arranged.spotlight}
          onOpen={onCourse}
          onFeature={onFeature}
          onUnfeature={onUnfeature}
        />
      )}

      {arranged.shelves.map((shelf) => (
        <Shelf
          key={shelf.key}
          shelf={shelf}
          onOpen={onCourse}
          onFeature={onFeature}
          onUnfeature={onUnfeature}
        />
      ))}

      {!isEmpty && arranged.matched === 0 && (
        <p role="status" className="text-sm text-fg-dim">
          Nothing in this catalog matches. Clear the search to see all {arranged.total} again.
        </p>
      )}

      {data.unnamedCount > 0 && (
        <div className="flex items-center gap-2">
          <Button small tone="quiet" onClick={() => setShowUnnamed((v) => !v)}>
            {showUnnamed ? 'Hide unnamed courses' : `Show ${data.unnamedCount} unnamed courses`}
          </Button>
        </div>
      )}

      <CatalogTools
        blurb={sweep.data ?? null}
        art={artSweep.data ?? null}
        startingBlurb={startSweep.isPending}
        startingArt={startArtSweep.isPending}
        onWriteCopy={() => startSweep.mutate()}
        onIllustrate={() => startArtSweep.mutate(false)}
        onReIllustrate={() => startArtSweep.mutate(true)}
      />
    </div>
  )
}

/** Card size per shelf. The three densities exist to make the page's own
 *  hierarchy legible -- curated cards are larger than highlights, which are
 *  larger than a category's members -- and `results` takes the middle one
 *  because a search result belongs to no tier. */
const SHELF_SIZE: Record<string, 'hero' | 'highlight' | 'filed'> = {
  hero: 'hero',
  highlights: 'highlight',
  results: 'highlight',
}

/** One shelf of cards under its heading.
 *
 * Shared by every section rather than written per section: the shelves differ
 * in what `arrangeCatalog` put in them and in nothing else. That is the whole
 * point of the arrangement being a fold -- the old page had `CandidateSection`
 * for two of the three and a hand-written row of category `Button`s for the
 * third, which is why filed categories were a wall of buttons that lost their
 * cards behind a click.
 */
const Shelf = ({
  shelf,
  onOpen,
  onFeature,
  onUnfeature,
}: {
  shelf: CatalogShelf
  onOpen: (slug: string) => void
  onFeature: (candidate: CourseCandidate) => void
  onUnfeature: (slug: string) => void
}) => (
  <section className="crs-shelf flex flex-col gap-2">
    <div className="flex items-baseline gap-2">
      <h2 className="font-semibold tracking-wide m-0 text-sm text-fg uppercase">{shelf.label}</h2>
      <span className="font-mono text-xs text-fg-faint">{shelf.candidates.length}</span>
      {shelf.curated && (
        // Said out loud, because the sort control is right there and does
        // nothing to this shelf. See `arrangeCatalog`'s docstring for why.
        <span className="text-xs text-fg-faint">in the order you featured them</span>
      )}
    </div>
    <div className="flex flex-wrap items-start gap-3">
      {shelf.candidates.map((candidate) => (
        <CourseCard
          key={candidate.slug}
          candidate={candidate}
          size={SHELF_SIZE[shelf.key] ?? 'filed'}
          onOpen={onOpen}
          onFeature={onFeature}
          onUnfeature={onUnfeature}
        />
      ))}
    </div>
  </section>
)

/** Realized courses re-clustering stranded -- see `OrphanedCourse`'s own
 *  docstring for why this strip is their only surface: the detail route looks
 *  up a slug in the *current* catalog and 404s for one of these. */
const OrphanedCoursesStrip = ({ courses }: { courses: readonly OrphanedCourse[] }) => (
  <div
    role="status"
    className="border-0 border-l-2 border-solid border-accent bg-bg-raise px-3 py-2 text-sm text-fg"
  >
    <p className="font-semibold">
      {courses.length} realized {courses.length === 1 ? 'course has' : 'courses have'} no cluster to
      show anymore:
    </p>
    <ul className="m-0 list-none p-0 text-fg-dim">
      {courses.map((course) => (
        <li key={course.slug}>
          {course.title} ({course.slug}) -- realized {realizedAgo(course.realizedAt)}
        </li>
      ))}
    </ul>
  </div>
)

/** "3 days ago", falling back to the raw value. Same guard and same reasoning
 *  as `CatalogSpotlight`'s `writtenAgo`: `date-fns` throws on an unparseable
 *  date, and this field crosses a wire. It replaces a `toLocaleDateString`,
 *  which printed a calendar date and left the reader to work out whether that
 *  was before or after the re-clustering that stranded the course -- which is
 *  the only question this line exists to answer. */
const realizedAgo = (iso: string): string => {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return iso
  return formatDistanceToNow(at, { addSuffix: true })
}
