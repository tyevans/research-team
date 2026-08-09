import type { ForkNode, SessionSummary } from '../session/session.ts'
import type { ProjectId } from '../shared/identifier.ts'
import type { Project } from './project.ts'

/** Arranging projects and sessions into the one thing the landing page is:
 *  projects, with their sessions inside them.
 *
 * Pure, and here rather than in a component, because every one of these
 * questions is about the model and not about a layout — which session belongs
 * to which project, which project was touched most recently, what a fork's
 * lineage is once its parent turns out to live somewhere else. A component
 * that answered them inline would answer them slightly differently in the two
 * places that ask.
 */

/** One project's sessions, and the numbers a row shows above them. */
export interface ProjectRollup {
  readonly project: Project
  /** The project's sessions as a forest, roots newest first. */
  readonly sessions: readonly ForkNode[]
  readonly sessionCount: number
  /** The sum of each session's live-file count.
   *
   * Not the number of distinct files in the project: sessions share a
   * filesystem, so a path two sessions both touched is counted twice. The
   * honest project-level number would need a fold the listing endpoint does
   * not do, and this one is still the right order of magnitude for "how much
   * work is in here" — which is all a stat line is scanned for. */
  readonly fileCount: number
  /** The newest session start in this project, ISO, or null if it has none.
   *
   * A session's summary carries when it *started* and nothing later, so this
   * moves when a session is created, forked or taken over rather than on every
   * turn. That is still the signal ranking wants — "where was I" resolves to
   * the project you most recently opened something in — but it is not the same
   * as "last turn", and a row must not claim it is. */
  readonly lastActivity: string | null
}

/** Every session, flattened out of the forest `/api/tree` answers.
 *
 * The nesting is rebuilt per project below, because a fork's parent may belong
 * to another project (or to none), and lineage that crossed a project boundary
 * would put a session inside a project it is not in. */
export const flatten = (nodes: readonly ForkNode[]): readonly SessionSummary[] =>
  nodes.flatMap((node) => [node as SessionSummary, ...flatten(node.children)])

/** Arrange sessions into the forest their fork lineage describes.
 *
 * The browser's copy of `build_fork_tree`, and it exists for the same reason
 * that one does: a session whose parent is absent from the input is a root
 * rather than a session that disappears. Here "absent" is the common case —
 * every partition is one project's sessions, so a fork made from a session in
 * a different project is a root of this one.
 */
export const forest = (summaries: readonly SessionSummary[]): readonly ForkNode[] => {
  const known = new Set(summaries.map((summary) => summary.id))
  const children = new Map<string, SessionSummary[]>()
  const roots: SessionSummary[] = []

  for (const summary of summaries) {
    const parent = summary.forkedFrom
    if (parent !== null && parent !== summary.id && known.has(parent)) {
      const siblings = children.get(parent)
      if (siblings) siblings.push(summary)
      else children.set(parent, [summary])
    } else {
      roots.push(summary)
    }
  }

  const node = (summary: SessionSummary): ForkNode => ({
    ...summary,
    // Children ascending: a fork tree read downwards is a story in the order it
    // happened. Only the roots are newest-first, because that list is scanned
    // rather than read.
    children: (children.get(summary.id) ?? [])
      .slice()
      .sort((a, b) => byStartAscending(a, b))
      .map(node),
  })

  return roots.sort((a, b) => byStartAscending(b, a)).map(node)
}

const byStartAscending = (a: SessionSummary, b: SessionSummary): number =>
  String(a.startedAt ?? '').localeCompare(String(b.startedAt ?? ''))

/** Every project, with its sessions inside it, ranked by last activity.
 *
 * A project with no sessions has no timestamp and sorts last — it is newly
 * created and has nothing in it, which is exactly where it belongs.
 *
 * Not ranked by liveness, though a run in flight is the most interesting thing
 * a row can say. Sorting a live project to the top means knowing whether every
 * project is live, including the four hundred nobody has scrolled to, and that
 * is a request per project on a listing that already folds one aggregate per
 * row server-side. The marker still appears where the project sorts; it is the
 * *ordering* that is deferred, until `/api/projects` carries activity itself.
 */
export const rollups = (
  projects: readonly Project[],
  summaries: readonly SessionSummary[],
): readonly ProjectRollup[] => {
  const grouped = new Map<ProjectId, SessionSummary[]>()
  for (const summary of summaries) {
    if (summary.projectId === null) continue
    const rows = grouped.get(summary.projectId)
    if (rows) rows.push(summary)
    else grouped.set(summary.projectId, [summary])
  }

  return projects
    .map((project): ProjectRollup => {
      const rows = grouped.get(project.id) ?? []
      return {
        project,
        sessions: forest(rows),
        sessionCount: rows.length,
        fileCount: rows.reduce((total, row) => total + (row.files ?? 0), 0),
        lastActivity: rows.reduce<string | null>(
          (newest, row) =>
            row.startedAt !== null && (newest === null || row.startedAt > newest)
              ? row.startedAt
              : newest,
          null,
        ),
      }
    })
    .sort((a, b) => String(b.lastActivity ?? '').localeCompare(String(a.lastActivity ?? '')))
}

/** The one session a project row shows without being asked.
 *
 * "Where was I" resolves to a project and then to a single session, and which
 * one that is deserves an answer rather than whichever happens to sort first:
 * the session *holding* the project, because that is the one still open and
 * the one `Resume` goes to, and the newest otherwise. A project whose holder
 * is missing from the summary list falls back to the newest rather than
 * showing nothing -- a row with no session reads as a project nothing has run
 * in, which would be a lie.
 */
export const currentSession = (rollup: ProjectRollup): SessionSummary | null => {
  const all = flatten(rollup.sessions)
  const holder = rollup.project.activeSessionId
  if (holder) {
    const held = all.find((session) => session.id === holder)
    if (held) return held
  }
  return all.reduce<SessionSummary | null>(
    (newest, session) =>
      newest === null || byStartAscending(session, newest) > 0 ? session : newest,
    null,
  )
}

export type Recency = 'today' | 'week' | 'older' | 'empty'

/** Which recency heading a project sits under.
 *
 * Computed from the same timestamp the row prints, so a row can never appear
 * under "Today" while reading "6d ago". The thresholds are calendar-agnostic
 * milliseconds, which is right for headings this coarse. */
export const recencyOf = (rollup: ProjectRollup, now: number): Recency => {
  if (rollup.lastActivity === null) return 'empty'
  const at = Date.parse(rollup.lastActivity)
  if (!Number.isFinite(at)) return 'older'
  const age = now - at
  if (age < 24 * 3600_000) return 'today'
  if (age < 7 * 24 * 3600_000) return 'week'
  return 'older'
}

/** Does this project, or any session in it, match what was typed?
 *
 * Sessions are searched by the only field a human wrote — the first message —
 * so "the one where I asked about spaced repetition" is a query that works.
 * Client-side over the query cache: the data is already here, and a search
 * endpoint for a list this size would be a request nobody needs. */
export const matches = (rollup: ProjectRollup, needle: string): boolean => {
  const query = needle.trim().toLowerCase()
  if (!query) return true
  if (rollup.project.name.toLowerCase().includes(query)) return true
  return flatten(rollup.sessions).some((session) =>
    (session.firstMessage ?? '').toLowerCase().includes(query),
  )
}
