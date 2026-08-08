import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { isBusy, nest, type WorkerNode } from '@domain/worker/worker.ts'
import { shortId, type ProjectId, type SessionId } from '@domain/shared/identifier.ts'

import { Chip } from '../common/primitives.tsx'

const POLL_MS = 2_000

/** Everything working on this project, right now.
 *
 * Polled rather than pushed: the roster is process-local state on the server,
 * and pushing it would mean making the session-keyed activity buffer
 * project-aware. What the poll sets the latency of is "a new worker appeared";
 * everything *inside* a worker arrives over the live feed.
 *
 * The one rule this component must not break: **a failed poll keeps the last
 * roster and marks it stale.** Rendering empty would say "nothing is running",
 * which is the specific lie this panel exists to kill.
 */
export const Workers = ({
  projectId,
  watching,
  onWatch,
}: {
  projectId: ProjectId
  watching: SessionId | null
  onWatch: (sessionId: SessionId | null) => void
}) => {
  const { workers } = useContainer()

  const roster = useQuery({
    queryKey: queryKeys.workers(projectId),
    queryFn: () => workers.on(projectId),
    refetchInterval: POLL_MS,
    // Keeping the previous data is what makes a failed poll stale rather than
    // empty. Retry is off so a failure is visible within one interval instead
    // of being hidden behind backoff.
    placeholderData: (previous) => previous,
    retry: false,
  })

  const current = roster.data ?? null
  const stale = roster.isError && current !== null

  if (!current && roster.isError) {
    return (
      <p className="sub worker-sub">
        Could not read what is running on this project. This build may not expose the roster.
      </p>
    )
  }

  return (
    <>
      <div className="worker-head">
        <h3 className="worker-title">Working now</h3>
        {stale ? (
          <Chip tone="run-short" title="The last poll failed; this is the last roster that arrived">
            stale
          </Chip>
        ) : isBusy(current) ? (
          <Chip tone="current">{current!.workers.length} running</Chip>
        ) : (
          <Chip>idle</Chip>
        )}
      </div>

      {current && current.workers.length > 0 ? (
        <ul className="worker-list">
          {nest(current.workers).map((node) => (
            <Row key={node.worker.ref} node={node} watching={watching} onWatch={onWatch} />
          ))}
        </ul>
      ) : (
        <p className="sub worker-sub">
          Nothing is running on this project.{' '}
          {current && current.idleSessionIds.length > 0
            ? `${current.idleSessionIds.length} session(s) attached and quiet.`
            : 'No sessions are attached.'}
        </p>
      )}
    </>
  )
}

const Row = ({
  node,
  watching,
  onWatch,
  nested = false,
}: {
  node: WorkerNode
  watching: SessionId | null
  onWatch: (sessionId: SessionId | null) => void
  nested?: boolean
}) => {
  const { worker } = node
  // Extraction opens the pane on the session that is hosting it, which is its
  // parent's. With no resolvable parent there is nothing to open, so the row
  // is text rather than a dead button.
  const target = worker.sessionId

  return (
    <>
      <li className={nested ? 'worker-row worker-child' : 'worker-row'}>
        <span className={`worker-dot worker-dot-${worker.kind}`} aria-hidden="true" />
        <span className="worker-kind">{worker.kind}</span>
        {target ? (
          <button
            type="button"
            className="btn btn-sm worker-open"
            aria-pressed={watching === target}
            onClick={() => onWatch(watching === target ? null : target)}
          >
            {worker.detail}
          </button>
        ) : (
          <span className="worker-detail">{worker.detail}</span>
        )}
        {target ? <span className="muted worker-ref">{shortId(target)}</span> : null}
      </li>
      {node.children.map((child) => (
        <Row key={child.worker.ref} node={child} watching={watching} onWatch={onWatch} nested />
      ))}
    </>
  )
}
