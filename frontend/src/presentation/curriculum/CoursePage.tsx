import { useEffect, useRef } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import { blurbAge } from '@domain/knowledge/catalog.ts'
import { fitSummary, outlineAge } from '@domain/knowledge/course.ts'
import { titleCase } from '@domain/knowledge/title-case.ts'
import { SessionId, type ProjectId } from '@domain/shared/identifier.ts'

import { Button, ErrorBox, Loading } from '../common/primitives.tsx'
import { projectHref, sessionSelection } from '../routing/routes.ts'
import { CourseMembers } from './CourseMembers.tsx'
import { CourseUnit } from './CourseUnit.tsx'

/** One cluster's course page: art and title, blurb, an outline, either
 *  "Make this course" or the realized state, and the cluster's membership as
 *  a fold -- what `#/p/<id>/course/<slug>` opens into.
 *
 * Its own component and its own fetch, matching `AreaDetail`'s reasoning: a
 * course's detail is a different response shape (`CourseDetail`, not
 * `LearningArea`) than the map already carries five names of, and folding
 * this into an existing pane would poll a projection that invalidates on
 * writes (realize, abandon, a blurb sweep) none of the others do.
 */
export const CoursePage = ({
  projectId,
  slug,
  onBack,
}: {
  projectId: ProjectId
  slug: string
  onBack: () => void
}) => {
  const { courses } = useContainer()
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: queryKeys.courseDetail(projectId, slug),
    queryFn: () => courses.course(projectId, slug),
  })

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.courseDetail(projectId, slug) })

  const realize = useMutation({
    mutationFn: () => courses.realize(projectId, slug),
    onSuccess: () => void invalidate(),
  })

  const abandon = useMutation({
    mutationFn: () => courses.abandon(projectId, slug),
    onSuccess: () => void invalidate(),
  })

  // Its own key and its own poll, matching `CatalogPane`'s `artSweep`
  // reasoning: a reroll reports four unrelated counts (always `total: 1`
  // here) and polling on `courseDetail`'s key would refetch the whole
  // detail page every two seconds instead of just this.
  const reroll = useQuery({
    queryKey: queryKeys.artReroll(projectId, slug),
    queryFn: () => courses.fetchArtReroll(projectId, slug),
    refetchInterval: (q) => (q.state.data?.running ? 2_000 : false),
  })

  const startReroll = useMutation({
    mutationFn: () => courses.startArtReroll(projectId, slug),
    onSuccess: (started) => queryClient.setQueryData(queryKeys.artReroll(projectId, slug), started),
  })

  // A poll transitioning `running: true` -> `false` is the one moment a
  // fresh `art.url` exists that `courseDetail`'s own cache does not know
  // about yet -- `CatalogPane`'s `artWasRunning`'s exact reasoning, narrowed
  // to one candidate.
  const rerollWasRunning = useRef(false)
  const rerollRunning = reroll.data?.running ?? false
  useEffect(() => {
    if (rerollWasRunning.current && !rerollRunning) void invalidate()
    rerollWasRunning.current = rerollRunning
  }, [rerollRunning]) // eslint-disable-line react-hooks/exhaustive-deps -- `invalidate` is a fresh closure every render; only `rerollRunning` should re-run this.

  if (query.isPending) return <Loading what="the course" />
  if (query.isError) {
    return (
      <ErrorBox
        heading="That course could not be read."
        message={query.error instanceof Error ? query.error.message : 'Unknown error.'}
        onRetry={() => void query.refetch()}
      />
    )
  }

  const detail = query.data
  const { candidate, outline, members, course } = detail
  const stale = blurbAge(candidate) === 'stale'
  const outlineStale = outlineAge(detail) === 'stale'

  return (
    // `min-h-0` and `overflow-y-auto`, exactly as `CatalogPane` and
    // `CurriculumPane` carry them: the `area` TabPanel owns no scroller, so a
    // page taller than the pane simply ran off the bottom with no way to
    // reach it. Shipped that way -- a realized course renders its whole unit
    // and every lesson here, which is the first content on this tab long
    // enough for the absence to matter.
    <div className="flex min-h-0 flex-col gap-3 overflow-y-auto p-3">
      <Button small onClick={onBack}>
        Back to catalog
      </Button>

      <div className="flex flex-col items-stretch gap-2">
        <img
          src={candidate.art.url}
          alt={candidate.art.alt}
          // See CLAUDE.md: no default Tailwind theme here, so a numbered
          // height utility like `h-56` would generate no CSS and collapse
          // this image silently -- an arbitrary value is the only kind that
          // works in this build.
          className="crs-course-art h-[224px] w-full rounded-md object-cover"
        />
        <div className="flex items-center gap-2">
          <Button
            small
            tone="quiet"
            onClick={() => startReroll.mutate()}
            disabled={startReroll.isPending || rerollRunning}
          >
            {rerollRunning ? 'Rerolling…' : 'Reroll art'}
          </Button>
          {reroll.data !== null &&
            reroll.data !== undefined &&
            !rerollRunning &&
            reroll.data.error !== null && (
              <p className="crs-course-reroll-error m-0 text-xs text-k-failure">
                The reroll failed: {reroll.data.error}
              </p>
            )}
          {reroll.data !== null &&
            reroll.data !== undefined &&
            !rerollRunning &&
            reroll.data.error === null &&
            reroll.data.failed > 0 && (
              <p className="crs-course-reroll-refused m-0 text-xs text-fg-dim">
                The model had nothing safe to offer -- the picture is unchanged.
              </p>
            )}
        </div>
        <h2 className="crs-course-title font-semibold text-2xl text-fg">
          {titleCase(candidate.title)}
        </h2>
        {candidate.blurb !== null && (
          <p className="crs-course-blurb text-sm text-fg-dim">
            {candidate.blurb.text}
            {stale && (
              <span className="crs-course-blurb-stale ml-1 text-xs text-fg-dim italic">
                (out of date)
              </span>
            )}
          </p>
        )}
      </div>

      {course === null ? (
        <div className="flex flex-col items-start gap-1">
          <Button onClick={() => realize.mutate()} disabled={realize.isPending}>
            Make this course
          </Button>
          {realize.isError && (
            <p className="crs-course-realize-error text-xs text-k-failure">
              {realize.error instanceof Error
                ? realize.error.message
                : 'Could not realize this course.'}
            </p>
          )}
        </div>
      ) : (
        <div
          // A directional width paired with `border-0`, not a plain
          // `border`: see CLAUDE.md's `border-solid` entry.
          className="crs-course-realized flex flex-col gap-1 rounded-md border-0 border-l-2 border-solid border-accent bg-bg-panel p-2 text-sm"
        >
          <p className="crs-course-realized-at m-0 text-fg">
            Made into a course on {new Date(course.realizedAt).toLocaleDateString()}.
          </p>
          <p className="crs-course-fit m-0 text-xs text-fg-dim">{fitSummary(course.fit)}</p>
          {course.authoredSessionId !== null && (
            // Demoted, not removed. It used to be the only way to reach the
            // authored text, which meant a reader wanting their course was
            // sent into an agent transcript; the course itself is now below,
            // and this is what it is -- a link to the working session, for
            // somebody debugging how the text came out that way.
            <a
              href={projectHref(projectId, sessionSelection(SessionId(course.authoredSessionId)))}
              className="crs-course-session focus-visible:lay-ring-inward text-xs text-fg-faint no-underline hover:underline"
            >
              Open the authoring session
            </a>
          )}
          <Button small tone="quiet" onClick={() => abandon.mutate()} disabled={abandon.isPending}>
            Abandon this course
          </Button>
        </div>
      )}

      {/* The owner's decision, and the reason it is one line: on a realized
          course's page the authored unit *replaces* the generated outline.
          The outline was a pitch to help somebody decide; once they have
          decided and the real thing exists, the pitch has done its job.
          Deliberately not both and deliberately no toggle -- two descriptions
          of one course, disagreeing, is worse than either.

          A realized course whose text is not written yet therefore shows
          neither: `CourseUnit` says nobody has written it, which is the true
          statement, where falling back to the outline would answer a question
          about the course with a description of the plan for it. */}
      {course !== null ? (
        <section className="crs-course-authored flex flex-col gap-2">
          <CourseUnit projectId={projectId} slug={slug} />
        </section>
      ) : (
        outline !== null && (
          <section className="crs-course-outline flex flex-col gap-2 rounded-md border border-line bg-bg-panel p-3">
            <p className="m-0 text-sm text-fg-dim">
              {outline.promise}
              {outlineStale && (
                <span className="crs-course-outline-stale ml-1 text-xs text-fg-dim italic">
                  (out of date)
                </span>
              )}
            </p>
            <ol className="m-0 flex list-decimal flex-col gap-2 pl-4">
              {outline.sections.map((section, index) => (
                <li key={index} className="text-sm text-fg">
                  <span className="font-medium">{section.heading}</span>
                  <p className="m-0 text-xs text-fg-dim">{section.summary}</p>
                </li>
              ))}
            </ol>
          </section>
        )
      )}

      <CourseMembers projectId={projectId} members={members} />
    </div>
  )
}
