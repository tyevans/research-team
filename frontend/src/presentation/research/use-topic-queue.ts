import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { queryKeys } from '@application/queries/keys.ts'
import {
  useCancelDispatch,
  useDispatchBoard,
  useDispatchTopic,
} from '@application/research/use-dispatch.ts'
import { useContainer } from '@app/container-context.tsx'
import { byUrgency, focusCounts, matchesTopic, type TopicFocus } from '@domain/research/topic.ts'
import type { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import { useFrameRefresh } from '../shell/use-frame-refresh.ts'

/** Everything the topic queue needs from the outside world, in one hook.
 *
 * The half of `TopicList` that talks to the container, extracted so the other
 * half is markup over props. Three queries, three mutations, a live-feed
 * subscription and the filter state, none of which `TopicQueue` can now reach
 * — which is the point: a presentational component that *can* fetch will,
 * eventually, and then it can only be rendered where a `QueryClientProvider`
 * and a real container exist.
 */
export const useTopicQueue = (projectId: ProjectId) => {
  const { topics } = useContainer()
  // The id of the topic being managed, not its detail: the detail is fetched
  // fresh (below) rather than reused from the list row, because the row's
  // `TopicView` leaves out the rationale, scope and sub-questions the dialog
  // needs and `TopicDetail` is what `TopicStatusDialog` was built to take.
  const [managing, setManaging] = useState<TopicId | null>(null)
  // Defaults to the whole queue rather than to `attention`: opening a page
  // already filtered would misreport how much work the project holds, and a
  // reader who has not chosen a filter should be looking at everything.
  const [focus, setFocus] = useState<TopicFocus>('all')
  const [search, setSearch] = useState('')

  const query = useQuery({
    queryKey: queryKeys.topics(projectId),
    queryFn: () => topics.list(projectId),
  })

  useTopicRefresh(projectId, managing)

  // Read unconditionally rather than only when something is running: the point
  // of the catch-up route is a tab that arrived *after* a dispatch started,
  // which cannot be detected without asking.
  const board = useDispatchBoard(projectId)
  const dispatching = useDispatchTopic(projectId)
  const cancelling = useCancelDispatch(projectId)

  const detail = useQuery({
    queryKey: managing ? queryKeys.topic(projectId, managing) : ['topic', 'none'],
    queryFn: () => topics.read(projectId, managing!),
    enabled: managing !== null,
  })

  const shown = useMemo(() => {
    const rows = query.data ?? []
    return rows.filter((topic) => matchesTopic(topic, focus, search)).sort(byUrgency)
  }, [query.data, focus, search])

  const counts = useMemo(() => focusCounts(query.data ?? []), [query.data])

  return {
    query,
    detail,
    managing,
    onManage: setManaging,
    onCloseManage: () => setManaging(null),
    queue: {
      topics: shown,
      counts,
      focus,
      search,
      dispatches: board.byTopic,
      // Narrowed to a boolean here rather than passed through: the queue's bar
      // says "1 running", not *which* one, and a presentational component
      // handed the whole `Dispatch` would be handed the temptation to say
      // more than the bar is for.
      running: board.running !== null,
      queuedCount: board.queuedCount,
      dispatching: dispatching.isPending,
      stopping: cancelling.isPending,
      onFocusChange: setFocus,
      onSearchChange: setSearch,
      onManage: setManaging,
      onStop: () => {
        cancelling.mutate()
      },
      onDispatch: (topicId: TopicId) => {
        dispatching.mutate({ topicId, action: 'understanding' })
      },
    },
  }
}

/** Re-read the queue when a topic frame says it moved.
 *
 * Two keys and no more. Re-reading everything on every frame would also fix
 * the bug, and would cost a request storm on a page that is simultaneously
 * drawing a force-directed graph and following an extraction — so the graph,
 * the documents and the seeding status are deliberately left alone: none of
 * them is what a topic frame changed.
 *
 * Scoped to `projectId` because a topic frame carries no project of its own
 * (see `topic_change` in `presenters.py`: only the creation event knows one,
 * and answering it per frame would be a read-model lookup on the connection
 * every browser holds open). The cost of that is a single extra list read when
 * another project's topic moves while this page is open, which is one request
 * against one query per frame on the server.
 *
 * `managing` is the topic whose detail dialog is open, if any -- the one other
 * cache entry a topic frame can stale. Its own key rather than a prefix over
 * `['topic', project]`, because only one dialog can be open and invalidating
 * the rest would refetch details nothing is showing.
 */
const useTopicRefresh = (projectId: ProjectId, managing: TopicId | null) => {
  const queryClient = useQueryClient()

  useFrameRefresh(
    // Always on: this hook lives in the pane it refreshes, so being mounted is
    // the "on screen" test `useTreeRefresh` needs its flag for.
    true,
    (frame) => frame.kind === 'topic',
    () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.topics(projectId) })
      if (managing) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.topic(projectId, managing) })
      }
    },
  )
}
