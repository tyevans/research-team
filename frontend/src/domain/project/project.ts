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

/** A project's position in the pipeline the system actually runs.
 *
 * The four stages are in dependency order and that ordering is the model,
 * not a presentation choice: seeding opens **topics**, investigating a topic
 * fetches **sources** into the corpus, extraction folds a source into the
 * graph (**extracted**), and the catalog realizes **courses** out of the
 * graph. Each stage consumes the one before it, so the four numbers read as a
 * position rather than as four unrelated totals.
 *
 * Every field is server-computed. None of it can be derived in the browser:
 * the counts live in four read models the console never fetches, and the
 * previous index's attempt to say something about a project from the session
 * list alone is exactly what produced "11 sessions, 30 files" — two numbers
 * about sessions standing in for everything a project is.
 */
export interface ProjectSummary {
  readonly topics: number
  /** Of `topics`, the ones opened and not yet investigated.
   *
   * The only number here that goes **down** as work happens, which is why it
   * is drawn differently from the rest: the other three accumulate, so a big
   * number is progress, and a big number here is a backlog. */
  readonly topicsOpen: number
  readonly sources: number
  /** Of `sources`, the ones folded into the knowledge graph.
   *
   * Never greater than `sources`. The *gap* is the point — ingest that has
   * happened with extraction not following it is a real and common state, and
   * it is the one thing on this page a reader can act on immediately. */
  readonly extracted: number
  readonly courses: number
  readonly sessions: number
  /** When this project was last *touched*, ISO, or null.
   *
   * The newest `updated_at` across its sessions, so it moves on every turn.
   * The landing page used to derive this from the newest session **start**,
   * and `landing.ts` carried a comment warning that a row "must not claim it
   * is" the last activity. Measured against a copy of the real database on
   * 2026-08-29: the two disagreed by up to 1h24m on a live project. */
  readonly lastActivity: string | null
}

/** A project as the index lists it: identity, holder, and its pipeline.
 *
 * Separate from `Project` rather than a field on it, mirroring the server
 * exactly: `GET /api/projects` carries a summary and `GET /api/projects/{id}`
 * does not. The asymmetry is the same one `ProjectDetail` makes in the other
 * direction, and for the same reason — a field belongs on the route that has
 * a reader for it. A project *page* has the project in front of it; an index
 * has six rows and nothing else to tell them apart.
 */
export interface ProjectListing extends Project {
  readonly summary: ProjectSummary
}

export const isHeld = (project: Project): boolean => project.activeSessionId !== null
