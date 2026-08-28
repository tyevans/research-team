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
 * **The obvious replacement does not work, and the reason is a guarantee
 * rather than an oversight.** Slice 4 asked whether this could become a
 * `useFrameRefresh` on `log`/`dispatch` frames, the way `useRunningAgents`
 * refreshes the global roster. It cannot, because a turn's events *append
 * atomically when the turn commits* (`session_service.run_turn`): while a
 * turn is running, the feed carries nothing about it at all. A `turn` worker
 * is in the roster for exactly the interval in which no frame can arrive, so
 * a frame-driven refresh would show it only after it had gone -- which is to
 * say, never. `tests/integration/test_turn_visibility.py::
 * test_a_turns_events_all_become_visible_at_once` is the measurement, and it
 * asserts the count of feed entries seen mid-turn is unchanged from before
 * it; it was run on 2026-08-14 rather than reasoned from. Extraction is the
 * same shape from the other side: it runs inside a turn and reports on
 * `Extraction` frames, which carry no feed position and are not `log`.
 *
 * What that costs, plainly: one request every two seconds per open course
 * page, mostly to be told nothing changed. It is paid because the alternative
 * is a panel that is silently wrong about the case it exists for.
 *
 * The same argument says the dock's frame-only refresh understates a turn's
 * liveness. That is the dock's bug, not an argument for copying it here.
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
