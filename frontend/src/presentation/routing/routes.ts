import { EventIndex, isEventIndex } from '@domain/session/event-index.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

/** The console's routes, as values rather than as strings.
 *
 * Every route here is a *linkable state*, which is the point: a scrub position
 * and an open file are in the URL so a reader can send somebody the exact thing
 * they are looking at. `#/s/<id>/at/12` and `#/s/<id>/file/<path>` are both
 * bookmarks, not click-only states.
 *
 * Hash-based because the backend serves one static file and knows nothing about
 * client paths — a history route would 404 on reload.
 */
export type Route =
  /** The landing page. Named for what it shows -- projects, with their
   *  sessions inside them -- rather than for the fork tree it used to lead
   *  with. The href is unchanged; only the name is honest now. */
  | { readonly name: 'home' }
  | {
      readonly name: 'session'
      readonly id: SessionId
      readonly at: ScrubPoint
      readonly path: FilePath | null
    }
  | {
      readonly name: 'course'
      readonly id: ProjectId
      /** The session whose transcript is open in the drawer, or null.
       *
       * In the URL for the reason the scrub point and the open file are: a
       * reader watching one worker should be able to send somebody the exact
       * screen, and a reload should not close the drawer. A path segment
       * rather than a query string because this parser handles segments and
       * has no query handling at all. */
      readonly watching: SessionId | null
    }
  | {
      readonly name: 'research'
      readonly id: ProjectId
      /** The entity whose neighbourhood is drawn and described, or null.
       *
       * In the URL for the reason the scrub point and the watched session are:
       * a graph somebody has browsed to is a thing worth sending, and a reload
       * that dropped it would throw away the search that found it. It is also
       * the seed the pane draws from on load -- an empty canvas and this
       * segment are the same state, so one field covers both. */
      readonly entity: string | null
    }

export const parseRoute = (hash: string): Route => {
  const parts = String(hash ?? '')
    .replace(/^#?\/?/, '')
    .split('/')
    .filter(Boolean)
    .map(decodeURIComponent)

  if (parts[0] === 's' && parts[1]) {
    const id = SessionId(parts[1])
    let rest = parts.slice(2)

    let at = ScrubPoint.head()
    if (rest[0] === 'at' && rest[1]) {
      const index = Number.parseInt(rest[1], 10)
      if (isEventIndex(index)) at = ScrubPoint.at(EventIndex(index))
      rest = rest.slice(2)
    }

    // A path may itself contain slashes, so everything after `file` is one
    // segment rejoined — splitting it into route parts would lose directories.
    const path = rest[0] === 'file' && rest[1] ? FilePath.of(rest.slice(1).join('/')) : null

    return { name: 'session', id, at, path }
  }

  // A course belongs to a project, not to the session that happens to be
  // driving it: the artifacts outlive any one session, so the route that shows
  // them is keyed the way they are stored.
  if (parts[0] === 'p' && parts[1] && parts[2] === 'course') {
    // A truncated `watching` with no id after it is still a course route: a
    // hand-edited URL should drop the drawer, not send somebody to the tree.
    const watching = parts[3] === 'watching' && parts[4] ? SessionId(parts[4]) : null
    return { name: 'course', id: ProjectId(parts[1]), watching }
  }

  // A research page belongs to a project for the same reason a course does:
  // what it shows -- topics, seeding, documents, the graph -- outlives any one
  // session, so it is keyed the way the material is stored, not the way it was
  // produced.
  if (parts[0] === 'p' && parts[1] && parts[2] === 'research') {
    // A truncated `entity` with no id after it is still a research page, the
    // way a truncated `watching` is still a course page: a hand-edited URL
    // should land on an empty canvas, not on the session tree.
    const entity = parts[3] === 'entity' && parts[4] ? parts[4] : null
    return { name: 'research', id: ProjectId(parts[1]), entity }
  }

  return { name: 'home' }
}

export const homeHref = (): string => '#/'

/** The scrub point and the open file are both in the URL, and both are
 *  optional.
 *
 * Carrying them together is what makes "the exact thing I am looking at"
 * linkable: a reader comparing one file across two points is looking at a
 * position *and* a document, and a link that dropped either would send somebody
 * to a different screen. It is also the reason neither needs a copy in
 * component state — the address bar is the single source of truth. */
export const sessionHref = (
  id: SessionId,
  at?: ScrubPoint | null,
  path?: FilePath | null,
): string => {
  let href = `#/s/${encodeURIComponent(id)}`
  if (at && at.kind === 'historical') href += `/at/${at.at}`
  if (path) href += `/file/${encodeURIComponent(path.value)}`
  return href
}

export const courseHref = (projectId: ProjectId, watching: SessionId | null = null): string =>
  watching
    ? `#/p/${encodeURIComponent(projectId)}/course/watching/${encodeURIComponent(watching)}`
    : `#/p/${encodeURIComponent(projectId)}/course`

export const researchHref = (projectId: ProjectId, entity: string | null = null): string =>
  entity
    ? `#/p/${encodeURIComponent(projectId)}/research/entity/${encodeURIComponent(entity)}`
    : `#/p/${encodeURIComponent(projectId)}/research`
