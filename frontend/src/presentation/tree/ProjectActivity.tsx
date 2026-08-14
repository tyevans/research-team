import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Chip } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
import { elapsed } from '../formatting/format.ts'

/** What is happening in a project right now, if anything.
 *
 * The one genuinely new read on this page, and the reason it is worth leaving
 * open. Rows already changed under the reader — turn counts ticked, file
 * counts ticked — with nothing to say why and nothing that said "a turn is
 * running in this project". The `ResearchRunDriver` is designed to run
 * unattended for a long time, so "come back and see what it did" is a
 * first-class arrival and the page it arrives on could not answer it.
 *
 * **One request for the whole page, not two per drawn row.** This used to ask
 * `research.current(projectId)` and `workers.on(projectId)` per row — `2N` per
 * render, re-paid on every debounced log burst, because `useTreeRefresh`
 * invalidates the `run` and `workers` prefixes both keys sit under. It now
 * reads `workers.everywhere()` under `queryKeys.runningAgents()`, which
 * `AgentWidget` already fetches unconditionally on every route, and picks this
 * project's roster out of it. React Query dedupes by key, so the sixteen rows a
 * virtualizer mounts at eight visible share one cache entry and the marker
 * costs **zero additional requests**.
 *
 * **What that costs is the round count.** `research.current` was the only
 * source of `run · round N`; the roster's run worker is `detail="autonomous
 * run"` with `startedAt=None` (`workers.py:296-303`), so a run now draws
 * `run running` with no elapsed suffix. The chip's job is "something is
 * happening here" and the round count is one click away on the project page.
 * Restoring it means widening `Worker` on the server, which is filed in
 * `BACKLOG.md` rather than dropped.
 *
 * The fix this comment used to name — an `activity` object on `/api/projects` —
 * was **not** taken. It is still the tidier answer (one read, no cross-page
 * sharing, and the round count survives) and it is still a backend change this
 * increment did not have room for.
 */
export const useProjectActivity = (
  projectId: ProjectId,
): { readonly live: boolean; readonly label: string | null } => {
  const { workers } = useContainer()

  // `retry: false`: a failed liveness read must not degrade the row. The row is
  // still a working link to four places, and an error where a chip would go
  // says nothing a reader can act on. The next invalidation asks again, which
  // is the whole recovery this needs.
  const rosters = useQuery({
    queryKey: queryKeys.runningAgents(),
    queryFn: () => workers.everywhere(),
    retry: false,
  })

  // `everywhere()` answers one entry per project that has something running and
  // omits the rest entirely, so "not found" is "nothing is running here" rather
  // than a gap. That is also why nothing below treats an absent roster as
  // "could not tell": the roster is process-local on the server, and an empty
  // one after a restart is the truth.
  const roster = rosters.data?.find((one) => one.projectId === projectId)

  // **A run outranks everything, which `workers[0]` would not have preserved.**
  // The two-query version checked `research.current` first and returned before
  // it ever looked at the roster, so a project with a run and a turn drew the
  // run. `everywhere()` sorts by project id and says nothing about the order
  // within a roster, so taking `[0]` would have made the label depend on
  // whatever order the server happened to fold in — a silent behaviour change
  // that no gate and no reader would attribute to this slice. Preferring `run`
  // explicitly keeps the old precedence and makes it a decision rather than an
  // accident. `ProjectActivity.test.tsx` fails if this becomes `[0]`.
  const worker = roster?.workers.find((one) => one.kind === 'run') ?? roster?.workers[0]
  if (!worker) return { live: false, label: null }
  const since = worker.startedAt ? elapsed(worker.startedAt) : ''
  const what = worker.kind === 'turn' ? 'turn running' : `${worker.kind} running`
  return { live: true, label: since ? `${what} · ${since}` : what }
}

/** The marker itself, in the amber the timeline already spends on tool
 *  activity — a run *is* tool activity, so liveness reads as the colour the
 *  event log uses for it rather than as a colour invented here. */
export const ActivityChip = ({ label }: { label: string | null }) =>
  label ? (
    <Tooltip explanation="Something is running in this project right now">
      <Chip tone="held">⟳ {label}</Chip>
    </Tooltip>
  ) : null
