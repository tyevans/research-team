import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { ProjectId } from '@domain/shared/identifier.ts'
import {
  remember,
  type TranscriptTail,
  type TranscriptTails,
} from '@domain/worker/transcript-tail.ts'
import type { Worker } from '@domain/worker/worker.ts'

import { useStream } from '../shell/StreamProvider.tsx'
import { useFrameRefresh } from '../shell/use-frame-refresh.ts'

/** One running agent, flattened out of the roster it arrived in. */
export interface RunningAgent {
  readonly worker: Worker
  readonly projectId: ProjectId
  /** The project's name, or null while it is not known. Null is a real state,
   *  not a loading one -- see `useRunningAgents` on why names are only fetched
   *  when the widget is open. */
  readonly projectName: string | null
  readonly tail: TranscriptTail | null
}

/** Everything running anywhere, with a sample of what each one is saying.
 *
 * **One request, not one per project.** `/api/workers` answers across every
 * project at once and only names the ones that have something running -- see
 * `WorkerRoster.everywhere`, which folds nothing when nothing is running. A
 * widget on every page cannot cost more than that.
 *
 * **Refreshed off the log frames the console is already receiving, never off a
 * timer.** The landing-page design doc records this decision and its reasoning
 * for its own per-row markers: a run's rounds *are* turns on a session, so the
 * frames that move a count are the frames that move the roster. A poll would
 * be a request per interval on every page, forever, mostly to be told that
 * nothing has changed.
 */
export const useRunningAgents = (
  /** Whether the widget is open. Almost everything here is gated on it -- see
   *  the two comments below, which are the reason this parameter exists rather
   *  than the hook simply doing its work. */
  expanded: boolean,
): {
  readonly agents: readonly RunningAgent[]
  readonly count: number
  readonly failed: boolean
} => {
  const { workers, projects } = useContainer()
  const queryClient = useQueryClient()

  // `retry: false` for `ProjectActivity`'s reason: a failed liveness read must
  // not be turned into something a reader is asked to act on. The next frame
  // asks again, which is the whole recovery this needs.
  const roster = useQuery({
    queryKey: queryKeys.runningAgents(),
    queryFn: () => workers.everywhere(),
    retry: false,
  })

  useFrameRefresh(
    true,
    (frame) => frame.kind === 'log' || frame.kind === 'dispatch',
    () => void queryClient.invalidateQueries({ queryKey: queryKeys.runningAgents() }),
  )

  // Project names cost a request against `/api/projects`, which folds one
  // aggregate per project server-side -- so it is only asked for once the
  // reader has opened the widget, and never on a page that merely renders the
  // collapsed count. On the landing page it is already in the cache and costs
  // nothing. Until it resolves a row names its project by short id, which is
  // why `projectName` is nullable rather than the row showing a spinner.
  const named = useQuery({
    queryKey: queryKeys.projects(),
    queryFn: () => projects.list(),
    enabled: expanded,
    retry: false,
  })

  const rosters = roster.data ?? []
  const tails = useTranscriptTails(expanded)

  const agents: RunningAgent[] = []
  for (const one of rosters) {
    for (const worker of one.workers) {
      agents.push({
        worker,
        projectId: one.projectId,
        projectName: named.data?.find((p) => p.id === one.projectId)?.name ?? null,
        tail: worker.sessionId ? (tails.get(worker.sessionId) ?? null) : null,
      })
    }
  }

  return {
    agents,
    count: agents.length,
    // Only a rejection counts as failure. An empty array is the ordinary
    // answer -- nothing is running -- and drawing it as an error would put a
    // red box on every page of an idle console.
    failed: roster.isError,
  }
}

/** The per-session sample, folded from frames rather than fetched.
 *
 * **Only while the widget is open.** Two costs are avoided by that, and both
 * are paid on every page otherwise: a state update per message-or-tool frame,
 * and the re-render it causes. The collapsed widget draws a count, which no
 * part of a transcript can change, so a closed widget does no work at all when
 * the log moves.
 *
 * Subscribed raw rather than through `useFrameRefresh`, which debounces: the
 * debounce is right for "re-read a list" and wrong for "fold the frame you
 * were handed", where waiting 400ms would drop every frame but the last of a
 * burst and the sample would skip whole tool calls.
 */
const useTranscriptTails = (expanded: boolean): TranscriptTails => {
  const stream = useStream()
  const [tails, setTails] = useState<TranscriptTails>(() => new Map())

  useEffect(() => {
    if (!expanded) return
    return stream.onFrame((frame) => {
      if (frame.kind !== 'log') return
      // Bounded inside `remember` by a size cap rather than filtered against
      // the running set here. Filtering needs the roster, which resolves after
      // the first frames can arrive -- doing it that way folded a frame in and
      // pruned it straight back out, and the row stayed blank. See MAX_TRACKED.
      setTails((known) => remember(known, frame.sessionId, frame.entry))
    })
  }, [expanded, stream])

  return tails
}

export type { TranscriptTail }
