import type { ProjectId, SessionId } from '../shared/identifier.ts'

/** One thing working on a project right now.
 *
 * Everything here is process-local on the server: a restart shows an empty
 * roster, which is the truth rather than a gap. That is also why an empty
 * roster and a failed poll must not render the same — see `Workers.tsx`.
 */
export interface Worker {
  readonly kind: 'run' | 'turn' | 'extraction'
  /** Identifies this worker within the roster: a run id, a session id, or a
   *  source id. Text because the three are different kinds of identifier and
   *  `parent` has to compare across them. */
  readonly ref: string
  /** What it is doing, composed by the server so two front ends cannot
   *  disagree about how to say the same thing. */
  readonly detail: string
  /** The session whose transcript is this worker's detail view. Null for
   *  extraction, whose detail view is the extraction pane. */
  readonly sessionId: SessionId | null
  readonly parent: string | null
  /** Epoch milliseconds, or null when the server had no start time. */
  readonly startedAt: number | null
}

export interface Roster {
  readonly projectId: ProjectId
  readonly workers: readonly Worker[]
  readonly idleSessionIds: readonly SessionId[]
}

export interface WorkerNode {
  readonly worker: Worker
  readonly children: readonly WorkerNode[]
}

/** Whether anything is actually working, as distinct from attached. */
export const isBusy = (roster: Roster | null): boolean => (roster?.workers.length ?? 0) > 0

/** Arrange workers into the containment the server described.
 *
 * A child whose parent is not present stays at the top level rather than being
 * dropped. The roster is polled, so a parent can disappear between the poll
 * that named it and this render, and a dropped child would hide live work —
 * the one thing this panel exists to prevent. A worker that names itself as
 * its own parent is treated the same way, so a bad server response cannot
 * produce a cycle here.
 */
export const nest = (workers: readonly Worker[]): readonly WorkerNode[] => {
  const present = new Set(workers.map((worker) => worker.ref))
  const children = new Map<string, Worker[]>()

  for (const worker of workers) {
    const parent = worker.parent
    if (parent === null || parent === worker.ref || !present.has(parent)) continue
    const siblings = children.get(parent)
    if (siblings) siblings.push(worker)
    else children.set(parent, [worker])
  }

  const nested = new Set(Array.from(children.values()).flat())

  return workers
    .filter((worker) => !nested.has(worker))
    .map((worker) => ({
      worker,
      children: (children.get(worker.ref) ?? []).map((child) => ({ worker: child, children: [] })),
    }))
}
