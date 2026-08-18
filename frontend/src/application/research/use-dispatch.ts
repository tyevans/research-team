import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'

import { useInteractionLog } from '@app/interaction-log-provider.tsx'
import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import { byTopic, type Dispatch } from '@domain/research/dispatch.ts'
import type { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import { useFrameRefresh } from '../../presentation/shell/use-frame-refresh.ts'

/** What this project has dispatched at its topics, live.
 *
 * A query invalidated off the live feed rather than a poll, matching
 * `useTopicRefresh`: every transition a dispatch makes is announced as a
 * `Dispatch` frame on the connection the shell already holds open. The
 * alternative — polling `/dispatch` — would keep a request in flight for
 * every open research pane whether or not anything was running, which is what
 * `Workers` has to do and does only because process state leaves no frame
 * behind. This one leaves a frame behind.
 *
 * **Invalidated rather than folded.** A frame carries one dispatch's new
 * state, so folding it into the cached board would be cheaper than a refetch
 * — and would need this hook to know that a `done` frame moves an entry from
 * `running` to `finished`, that a `queued` one renumbers everything behind
 * it, and that a `cancelled` one removes it. That is the server's own
 * bookkeeping restated in the browser, and the two would disagree the first
 * time either changed. One read of a route that answers all three lists is
 * the same answer a reload would give.
 */
export const useDispatchBoard = (projectId: ProjectId) => {
  const { topics } = useContainer()
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: queryKeys.dispatch(projectId),
    queryFn: () => topics.dispatchStatus(projectId),
  })

  useFrameRefresh(
    true,
    (frame) => frame.kind === 'dispatch' && frame.projectId === projectId,
    () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.dispatch(projectId) })
      // A finished dispatch has written a file and may have recorded findings
      // on its topic. The findings arrive as topic frames and `useTopicRefresh`
      // reads those; the file does not move the topic list at all, which is
      // why this does not invalidate it here. See `ResearchView` for where the
      // written file becomes reachable.
    },
  )

  /** Every topic's current dispatch, by topic id.
   *
   * Finished first so that running and queued overwrite it: a topic
   * dispatched a second time should show what is happening now, not how the
   * last one went. `byTopic` documents the last-write-wins rule this relies
   * on.
   */
  const current = useMemo((): ReadonlyMap<string, Dispatch> => {
    const board = query.data
    if (!board) return new Map()
    return byTopic([...board.finished, ...board.queued, ...(board.running ? [board.running] : [])])
  }, [query.data])

  return {
    board: query.data,
    byTopic: current,
    isPending: query.isPending,
    running: query.data?.running ?? null,
    queuedCount: query.data?.queued.length ?? 0,
  }
}

/** Press a dispatch action on one topic.
 *
 * The cache is invalidated on success rather than updated with the returned
 * dispatch, for the reason above: the 202 says "queued", and by the time it
 * lands the server may already have started it. Writing the stale answer in
 * would show a position that the very next frame corrects.
 */
export const useDispatchTopic = (projectId: ProjectId) => {
  const { topics } = useContainer()
  const queryClient = useQueryClient()
  const log = useInteractionLog()

  return useMutation({
    mutationFn: ({ topicId, action }: { topicId: TopicId; action: string }) =>
      topics.dispatch(projectId, topicId, action),
    onSuccess: (_result, { topicId, action }) => {
      log.record('DispatchRequested', { topic_id: topicId, action })
      return queryClient.invalidateQueries({ queryKey: queryKeys.dispatch(projectId) })
    },
  })
}

/** Stop what is running and drop what is queued, for this project. */
export const useCancelDispatch = (projectId: ProjectId) => {
  const { topics } = useContainer()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => topics.cancelDispatch(projectId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.dispatch(projectId) }),
  })
}
