import { shortId } from '@domain/shared/identifier.ts'
import type { SessionProjection } from '@domain/session/session.ts'
import { forkOrigin } from '@domain/session/session.ts'
import type { Course } from '@domain/project/course.ts'

import type { Route } from '../routing/routes.ts'
import { courseHref, researchHref, sessionHref, treeHref } from '../routing/routes.ts'

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
  if (route.name === 'course') {
    return (
      <nav className="crumbs" id="crumbs">
        <a href={treeHref()}>sessions</a>
        <span className="sep">/</span>
        <span className="sid">{course?.projectName || shortId(route.id)}</span>
        <span className="sep">/</span>
        <span className="sep">course</span>
      </nav>
    )
  }

  if (route.name === 'research') {
    return (
      <nav className="crumbs" id="crumbs">
        <a href={treeHref()}>sessions</a>
        <span className="sep">/</span>
        <span className="sid">{course?.projectName || shortId(route.id)}</span>
        <span className="sep">/</span>
        <span className="sep">research</span>
      </nav>
    )
  }

  if (route.name !== 'session') {
    return (
      <nav className="crumbs" id="crumbs">
        <span className="sep">fork tree</span>
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
      <a href={treeHref()}>sessions</a>
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
          <a href={courseHref(projectId)}>course</a>
          <span className="sep">·</span>
          <a href={researchHref(projectId)}>research</a>
        </>
      ) : null}
    </nav>
  )
}
