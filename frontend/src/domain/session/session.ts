import type { ProjectId, SessionId } from '../shared/identifier.ts'
import type { Message } from '../conversation/message.ts'
import type { WorkspaceFile } from '../workspace/workspace-file.ts'
import type { EventIndex } from './event-index.ts'

/** A session folded to one point: HEAD, or an event the reader scrubbed to.
 *
 * The same type serves both because they *are* the same projection — the server
 * folds to a point and answers with this shape either way, and every pane that
 * reads it asks the same questions of it. What differs is only which one the
 * `ScrubPoint` says to render, which is the reader's state and not the fold's.
 */
export interface SessionProjection {
  readonly id: SessionId
  readonly projectId: ProjectId | null
  /** Process facts, not log facts. `null` means the caller did not ask. */
  readonly holdsProject: boolean | null
  readonly knowledgeAttached: boolean | null
  readonly modelName: string | null
  readonly systemPrompt: string | null
  readonly turnIndex: number
  readonly failedTurns: number
  readonly forkedFrom: SessionId | null
  readonly forkedAt: number | null
  readonly eventCount: number
  /** How many leading messages the model now sees as a summary instead. */
  readonly compactedThrough: number | null
  readonly compactionSummary: string | null
  readonly at: number | null
  readonly files: readonly WorkspaceFile[]
  readonly messages: readonly Message[]
}

/** One node of the fork tree, and one row of the session list.
 *
 * The two endpoints answer the same fields; the tree adds children. Modelling
 * them as one type is what lets the list stand in for the tree when the
 * projection behind `/api/tree` has drifted — which is the fallback the console
 * has always had and which a second type would have made a second code path. */
export interface SessionSummary {
  readonly id: SessionId
  /** The project this session shares a filesystem and knowledge graph with.
   *
   * The key the landing page groups on: a session row that cannot name its
   * project can only be listed beside the projects, never inside one. `null`
   * is a session belonging to no project, which is a state and not a gap. */
  readonly projectId: ProjectId | null
  readonly startedAt: string | null
  readonly turns: number | null
  readonly files: number | null
  readonly firstMessage: string | null
  readonly forkedFrom: SessionId | null
  readonly forkedAt: number | null
  readonly failedTurns: number | null
}

export interface ForkNode extends SessionSummary {
  readonly children: readonly ForkNode[]
}

/** Total events at HEAD.
 *
 * The server's declared count and the fetched log's length can disagree
 * briefly mid-turn, and the larger is always the honest answer: a log shorter
 * than the count is one this tab has not caught up with, and a count shorter
 * than the log cannot happen. */
export const totalEvents = (declared: number | null | undefined, fetched: number): number =>
  typeof declared === 'number' ? Math.max(declared, fetched) : fetched

/** How many leading messages sit behind the compaction boundary.
 *
 * Clamped to the messages actually held, so a stale or oversized count from a
 * scrubbed fold can never swallow the whole conversation. */
export const compactedThrough = (
  declared: number | null | undefined,
  messageCount: number,
): number => {
  if (typeof declared !== 'number' || !Number.isFinite(declared) || declared <= 0) return 0
  return Math.min(Math.floor(declared), messageCount)
}

/** The fork this session came from, if any — the crumb trail's second half. */
export const forkOrigin = (
  session: SessionProjection | null,
): { readonly from: SessionId; readonly at: EventIndex | null } | null => {
  if (!session?.forkedFrom) return null
  return {
    from: session.forkedFrom,
    at: typeof session.forkedAt === 'number' ? (session.forkedAt as EventIndex) : null,
  }
}
