import { useQuery } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Markdown } from '../common/content.tsx'
import { ErrorBox, Loading } from '../common/primitives.tsx'

/** What the three UbD authoring turns actually wrote for a realized course,
 *  on the page rather than in a zip.
 *
 * The gap this closes is the one CLAUDE.md would call a silent absence: the
 * unit markdown has existed in the authoring session's workspace since the
 * feature shipped, `export.py` could resolve it, and the only door out of the
 * system was a download or a link into the agent transcript. A catalog that
 * looks finished made that read as polish rather than as a missing half.
 *
 * Its own component and its own query rather than a field on the detail, for
 * `useLesson`'s reason: the detail response is invalidated by realize,
 * abandon, a blurb sweep and an art reroll, four writes that change nothing
 * about the text -- and this is the largest payload on the page.
 */
export const CourseUnit = ({ projectId, slug }: { projectId: ProjectId; slug: string }) => {
  const { courses } = useContainer()

  const query = useQuery({
    queryKey: queryKeys.courseText(projectId, slug),
    queryFn: () => courses.courseText(projectId, slug),
    // Only while a run is genuinely writing *this* course. The server decides
    // that (see `read_course_unit`), so a path run over eight other areas does
    // not put this page into a poll it will never leave. Three seconds rather
    // than the two the art reroll uses: an authoring turn is a model call
    // measured in tens of seconds, and a faster poll would only be a busier
    // one.
    refetchInterval: (q) => (q.state.data?.state === 'authoring' ? 3_000 : false),
  })

  if (query.isPending) return <Loading what="the course text" />
  if (query.isError) {
    return (
      <ErrorBox
        heading="The course text could not be read."
        message={query.error instanceof Error ? query.error.message : 'Unknown error.'}
        onRetry={() => void query.refetch()}
      />
    )
  }

  const text = query.data

  if (text.state === 'authoring') {
    return (
      <p className="crs-course-authoring text-fg-muted m-0 text-sm">
        This course is being written now. It will appear here when the turns finish.
      </p>
    )
  }

  if (text.state === 'unauthored') {
    // Deliberately not "no course yet" or an empty panel. The one thing a
    // reader has to be able to tell from the line above is that *nobody has
    // started*, because that is the difference between waiting and asking for
    // it -- see `CourseTextState` for why the outline's nullable field could
    // not carry this.
    return (
      <p className="crs-course-unauthored m-0 text-sm text-fg-faint">
        Nobody has written this course yet.
      </p>
    )
  }

  return (
    <article className="crs-course-text flex flex-col gap-4">
      {text.unit === null ? (
        // `authored` with no unit is a real state, not an absence: the framing
        // turn can fail while the lesson turns land. Saying so beats rendering
        // the lessons under nothing and letting a reader assume the unit was
        // never part of the shape.
        <p className="crs-course-no-unit m-0 text-sm text-fg-faint">
          The framing for this course was not written -- its lessons are below.
        </p>
      ) : (
        <Markdown source={text.unit} projectId={projectId} className="crs-course-unit" />
      )}
      {text.lessons.map((lesson) => (
        // Keyed on the workspace path, not on the heading: two lessons can
        // open with the same words, and a heading key would collapse them.
        <Markdown
          key={lesson.path}
          source={lesson.markdown}
          projectId={projectId}
          className="crs-course-lesson"
        />
      ))}
    </article>
  )
}
