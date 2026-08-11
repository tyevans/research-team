import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { WorkerList, WorkerListUnavailable } from './WorkerList.tsx'

const POLL_MS = 2_000

/** Everything working on this project, right now.
 *
 * Polled rather than pushed: the roster is process-local state on the server,
 * and pushing it would mean making the session-keyed activity buffer
 * project-aware. What the poll sets the latency of is "a new worker appeared";
 * everything *inside* a worker arrives over the live feed.
 *
 * This component is now only the poll. What it looks like is `WorkerList`,
 * which takes the roster as a prop -- so the states that matter here (stale,
 * stale-and-empty, never-arrived) are reachable without a fake repository.
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
    // A failed refetch keeps the last successful `data` and sets `error`
    // alongside it — TanStack Query does this on its own, with nothing to opt
    // into here — which is what lets this render the last roster with a stale
    // marker instead of emptying. Retry is off so that failure is visible
    // within one interval instead of being hidden behind backoff.
    retry: false,
  })

  const current = roster.data ?? null

  if (!current && roster.isError) return <WorkerListUnavailable />

  return (
    <WorkerList
      roster={current}
      stale={roster.isError && current !== null}
      watching={watching}
      onWatch={onWatch}
    />
  )
}
