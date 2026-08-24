import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import { blurbAge } from '@domain/knowledge/catalog.ts'
import { fitSummary, outlineAge } from '@domain/knowledge/course.ts'
import { titleCase } from '@domain/knowledge/title-case.ts'
import { SessionId, type ProjectId } from '@domain/shared/identifier.ts'

import { Button, ErrorBox, Loading } from '../common/primitives.tsx'
import { projectHref, sessionSelection } from '../routing/routes.ts'

/** One cluster's course page: art and title, blurb, an outline, either
 *  "Make this course" or the realized state, and the cluster's full
 *  membership -- what `#/p/<id>/course/<slug>` opens into.
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
    <div className="flex flex-col gap-3 p-3">
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
        <h2 className="crs-course-title font-semibold text-2xl text-fg">
          {titleCase(candidate.title)}
        </h2>
        {candidate.blurb !== null && (
          <p className="crs-course-blurb text-fg-muted text-sm">
            {candidate.blurb.text}
            {stale && (
              <span className="crs-course-blurb-stale text-fg-muted ml-1 text-xs italic">
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
            <p className="crs-course-realize-error text-danger text-xs">
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
          <p className="crs-course-fit text-fg-muted m-0 text-xs">{fitSummary(course.fit)}</p>
          {course.authoredSessionId !== null ? (
            <a
              href={projectHref(projectId, sessionSelection(SessionId(course.authoredSessionId)))}
              className="crs-course-session focus-visible:lay-ring-inward text-xs text-fg no-underline hover:underline"
            >
              Open the authored session
            </a>
          ) : (
            <p className="crs-course-no-session m-0 text-xs text-fg-faint">Not authored yet.</p>
          )}
          <Button small tone="quiet" onClick={() => abandon.mutate()} disabled={abandon.isPending}>
            Abandon this course
          </Button>
        </div>
      )}

      {outline !== null && (
        <section className="crs-course-outline flex flex-col gap-2 rounded-md border border-line bg-bg-panel p-3">
          <p className="text-fg-muted m-0 text-sm">
            {outline.promise}
            {outlineStale && (
              <span className="crs-course-outline-stale text-fg-muted ml-1 text-xs italic">
                (out of date)
              </span>
            )}
          </p>
          <ol className="m-0 flex list-decimal flex-col gap-2 pl-4">
            {outline.sections.map((section, index) => (
              <li key={index} className="text-sm text-fg">
                <span className="font-medium">{section.heading}</span>
                <p className="text-fg-muted m-0 text-xs">{section.summary}</p>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section className="crs-course-members flex flex-col gap-1">
        <h3 className="font-medium m-0 text-sm">{members.length} entities in this cluster</h3>
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {members.map((member) => (
            <li key={member.entityId} className="flex items-baseline gap-2 text-xs">
              <a
                href={projectHref(projectId, { facet: 'entity', id: member.entityId })}
                className="focus-visible:lay-ring-inward text-fg no-underline hover:underline"
              >
                {member.name}
              </a>
              <span className="text-fg-faint">{member.entityType}</span>
              {member.temporal !== null && <span className="text-fg-faint">{member.temporal}</span>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
