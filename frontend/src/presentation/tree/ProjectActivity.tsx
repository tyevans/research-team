import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { isLive } from '@domain/research/run.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Chip } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
import { elapsed } from '../formatting/format.ts'

/** What is happening in a project right now, if anything.
 *
 * The one genuinely new read on this page, and the reason it is worth leaving
 * open. Rows already changed under the reader — turn counts ticked, file
 * counts ticked — with nothing to say why and nothing that said "a turn is
 * running in this project". The `AutoResearchDriver` is designed to run
 * unattended for a long time, so "come back and see what it did" is a
 * first-class arrival and the page it arrives on could not answer it.
 *
 * Two requests per rendered row, on a listing endpoint that already folds one
 * aggregate per project server-side. That cost is real and it is why this only
 * asks for rows the virtualizer has actually drawn: a project scrolled past is
 * not polled. The right fix is an `activity` object on `/api/projects`, which
 * is a larger piece of work than a landing page.
 */
export const useProjectActivity = (
  projectId: ProjectId,
  enabled: boolean,
): { readonly live: boolean; readonly label: string | null } => {
  const { research, workers } = useContainer()

  // `retry: false` on both: a failed liveness read must not degrade the row.
  // The row is still a working link to four places, and an error where a chip
  // would go says nothing a reader can act on. The next invalidation asks
  // again, which is the whole recovery this needs.
  const run = useQuery({
    queryKey: queryKeys.run(projectId),
    queryFn: () => research.current(projectId),
    enabled,
    retry: false,
  })
  const roster = useQuery({
    queryKey: queryKeys.workers(projectId),
    queryFn: () => workers.on(projectId),
    enabled,
    retry: false,
  })

  const running = isLive(run.data ?? null)
  if (running) {
    const rounds = run.data?.progress?.rounds
    return { live: true, label: typeof rounds === 'number' ? `run · round ${rounds}` : 'run' }
  }

  // The roster is process-local on the server, so an empty one after a restart
  // is the truth rather than a gap — which is why nothing here treats "no
  // workers" as "could not tell".
  const worker = roster.data?.workers[0]
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
