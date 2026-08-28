import type { ProjectId, SessionId } from '../shared/identifier.ts'

/** A shared filesystem and knowledge graph. One session holds it at a time.
 *
 * The holder is part of the model rather than looked up separately, because it
 * decides what the project can *offer*: a held project has two honest choices
 * (open the holder, or end it and take over) where a free one has one. A list
 * that could not see the holder would show a single "join" button and no way to
 * know that pressing it will fail.
 */
export interface Project {
  readonly id: ProjectId
  readonly name: string
  readonly activeSessionId: SessionId | null
  readonly tipAtEvent: number
}

/** One project's page, which needs one thing a row does not: somewhere to read
 *  its files from.
 *
 * **`readingHeadSessionId` is not the holder, and that is the point.** Every
 * file reader in this console is keyed by `(sessionId, path)`, and a project's
 * files live on whichever session last wrote them — the holder while somebody
 * holds it, the tip session between sessions. The server resolves that once
 * (`presenters.reading_head`) so the console reuses the session-keyed routes
 * unchanged instead of growing a project-scoped copy of each.
 *
 * It is a session and no scrub point. The pair used to travel together and the
 * offset half was measured wrong on 2026-08-27: it named a point at which a
 * file the same response listed did not exist. HEAD is the answer in every
 * branch, so callers write `ScrubPoint.head()` rather than reading one back.
 *
 * `null` for a project that has never been joined — which is exactly the
 * project with no files either.
 *
 * **Not on the listing**, deliberately. `GET /api/projects` folds one aggregate
 * per row, `landing.ts` already defers a feature on that cost, and no listing
 * surface reads a file. This is why `Project` is an interface again rather than
 * the alias of this type it was for two slices.
 */
export interface ProjectDetail extends Project {
  readonly readingHeadSessionId: SessionId | null
}

export const isHeld = (project: Project): boolean => project.activeSessionId !== null
