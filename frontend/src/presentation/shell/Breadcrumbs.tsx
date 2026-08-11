import { shortId } from '@domain/shared/identifier.ts'
import type { SessionProjection } from '@domain/session/session.ts'
import { forkOrigin } from '@domain/session/session.ts'
import type { Course } from '@domain/project/course.ts'

import type { Route } from '../routing/routes.ts'
import { projectHref, sessionHref, homeHref } from '../routing/routes.ts'

/** Where you are, and the one link back.
 *
 * The fork origin is part of the trail rather than a detail in a panel: a
 * forked session's most useful fact is what it came from and where it diverged,
 * and that is a navigation question. */
export const Breadcrumbs = ({
  route,
  session,
  course,
}: {
  route: Route
  session: SessionProjection | null
  course: Course | null
}) => {
  if (route.name === 'project') {
    const facet = route.selection?.facet ?? null
    return (
      <nav className="crumbs" id="crumbs">
        <a href={homeHref()}>projects</a>
        <span className="sep">/</span>
        {/* The project's own crumb is a link now rather than dead text: with a
            facet selected there is somewhere for it to go — the same project
            with nothing selected — and that is the step a reader wants after
            following a link into one topic. */}
        {facet ? (
          <a className="sid" href={projectHref(route.id)}>
            {course?.projectName || shortId(route.id)}
          </a>
        ) : (
          <span className="sid">{course?.projectName || shortId(route.id)}</span>
        )}
        {facet ? (
          <>
            <span className="sep">/</span>
            {/* The facet, not the id. A crumb is for getting back, and the id
                is already on the page that drew it. */}
            <span className="sep">{facet}</span>
          </>
        ) : null}
      </nav>
    )
  }

  if (route.name !== 'session') {
    return (
      <nav className="crumbs" id="crumbs">
        <span className="sep">projects</span>
      </nav>
    )
  }

  const origin = forkOrigin(session)
  // A session belonging to a project can reach that project's two pages from
  // here. The course and research pages both link to each other and neither
  // could be reached from a transcript at all, so watching a worker was a
  // one-way trip -- you got there from the project and then had to go back
  // through the session tree to return to it.
  //
  // In the breadcrumb rather than beside the scrub bar because this is a
  // navigation question, which is what the trail already answers. The project
  // is named by its id: a transcript knows which project it belongs to, but
  // not what that project is called, and fetching a name to label a link would
  // make every session load wait on a request it otherwise does not need.
  const projectId = session?.projectId ?? null
  return (
    <nav className="crumbs" id="crumbs">
      <a href={homeHref()}>projects</a>
      <span className="sep">/</span>
      <span className="sid">{shortId(route.id)}</span>
      {origin ? (
        <>
          <span className="sep">← forked from</span>
          <a href={sessionHref(origin.from)}>
            {shortId(origin.from)}
            {origin.at !== null ? ` @${origin.at}` : ''}
          </a>
        </>
      ) : null}
      {projectId ? (
        <>
          <span className="sep">/</span>
          <a href={projectHref(projectId)}>course</a>
          <span className="sep">·</span>
          <a href={projectHref(projectId, { facet: 'entity', id: null })}>research</a>
        </>
      ) : null}
    </nav>
  )
}
