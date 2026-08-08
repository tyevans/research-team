import { shortId } from '@domain/shared/identifier.ts'
import type { SessionProjection } from '@domain/session/session.ts'
import { forkOrigin } from '@domain/session/session.ts'
import type { Course } from '@domain/project/course.ts'

import type { Route } from '../routing/routes.ts'
import { sessionHref, treeHref } from '../routing/routes.ts'

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
    </nav>
  )
}
