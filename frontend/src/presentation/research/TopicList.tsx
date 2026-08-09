import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import {
  byUrgency,
  focusCounts,
  isClosed,
  matchesTopic,
  type TopicFocus,
  type TopicView,
} from '@domain/research/topic.ts'
import type { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import { Button, EmptyState, ErrorBox, Loading } from '../common/primitives.tsx'
import { useFrameRefresh } from '../shell/use-frame-refresh.ts'
import { TopicStatusDialog } from './TopicStatusDialog.tsx'

/** The project's topic queue, ranked by `byUrgency`: blocked topics first,
 *  then ones flagged for attention, then everything still live, then
 *  everything closed.
 *
 * A query refreshed off the live feed rather than a poll: `Workers` polls
 * because process state leaves no event behind, but a topic opening or moving
 * *is* a log entry, so the frames that change this list are already on the
 * connection the shell holds open. `useTopicRefresh` below is what reads them
 * — without it this list only changed on a manual action or a reload, which
 * is exactly what a reader watching a seeding run saw.
 */
export const TopicList = ({ projectId }: { projectId: ProjectId }) => {
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

  const detail = useQuery({
    queryKey: managing ? queryKeys.topic(projectId, managing) : ['topic', 'none'],
    queryFn: () => topics.read(projectId, managing!),
    enabled: managing !== null,
  })

  // Ranked and filtered above the early returns, because hooks cannot run
  // after them. `query.data` is undefined until the fetch lands, and the
  // result is thrown away by the `isPending` branch below.
  const shown = useMemo(() => {
    const rows = query.data ?? []
    return rows.filter((topic) => matchesTopic(topic, focus, search)).sort(byUrgency)
  }, [query.data, focus, search])

  const counts = useMemo(() => focusCounts(query.data ?? []), [query.data])

  if (query.isPending) return <Loading what="topics" />

  if (query.isError) {
    return (
      <ErrorBox
        title="Could not read this project's topics"
        message={query.error instanceof Error ? query.error.message : String(query.error)}
        onRetry={() => void query.refetch()}
      />
    )
  }

  if (query.data.length === 0) {
    return <EmptyState title="No topics" detail="Nothing has been seeded into this queue yet." />
  }

  return (
    <div className="topic-browser">
      <div className="topic-filters">
        <input
          type="search"
          className="input topic-search"
          placeholder="Filter topics"
          aria-label="Filter topics"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        {/* A radio group, not a row of buttons: these four are one choice with
            one answer, and that is what a screen reader should be told. The
            count rides on the label so an empty slice announces itself as
            empty before it is picked. */}
        <div className="topic-focus" role="radiogroup" aria-label="Which topics to show">
          {FOCUSES.map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={focus === value}
              className={focus === value ? 'topic-focus-tab is-on' : 'topic-focus-tab'}
              onClick={() => setFocus(value)}
            >
              {label} <span className="topic-focus-count">{counts[value]}</span>
            </button>
          ))}
        </div>
      </div>

      {shown.length === 0 ? (
        // Distinct from "No topics" above, and the distinction is the whole
        // point: that one means the queue is empty, this one means the queue
        // has work in it that the current filter is hiding.
        <EmptyState
          title="No topics match"
          detail="Nothing in this project matches that filter. Widen it to see the rest of the queue."
        />
      ) : (
        <ul className="topic-list">
          {shown.map((topic) => (
            <TopicRow
              key={topic.topicId}
              topic={topic}
              onManage={() => setManaging(topic.topicId)}
            />
          ))}
        </ul>
      )}
      {/* Rendered only once the detail has actually loaded -- opening on the
          click and closing the moment `read` resolves would flash a dialog
          with nothing in it, and `TopicStatusDialog` requires a `TopicDetail`
          to render at all. */}
      {managing && detail.data ? (
        <TopicStatusDialog
          projectId={projectId}
          topic={detail.data}
          onClose={() => setManaging(null)}
        />
      ) : null}
    </div>
  )
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
 * every browser holds open). The cost of that is a single extra list read
 * when another project's topic moves while this page is open, which is one
 * request against one query per frame on the server.
 *
 * `managing` is the topic whose detail dialog is open, if any -- the one
 * other cache entry a topic frame can stale. Its own key rather than a
 * prefix over `['topic', project]`, because only one dialog can be open and
 * invalidating the rest would refetch details nothing is showing.
 */
const useTopicRefresh = (projectId: ProjectId, managing: TopicId | null) => {
  const queryClient = useQueryClient()

  useFrameRefresh(
    // Always on: this hook lives in the pane it refreshes, so being mounted
    // is the "on screen" test `useTreeRefresh` needs its flag for.
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

/** The slices, in the order they are offered: everything, then the one that
 *  wants a person, then what is still moving, then what is done with. */
const FOCUSES: readonly (readonly [TopicFocus, string])[] = [
  ['all', 'All'],
  ['attention', 'Needs you'],
  ['live', 'Live'],
  ['closed', 'Closed'],
]

const TopicRow = ({ topic, onManage }: { topic: TopicView; onManage: () => void }) => (
  <li
    className={
      topic.isBlocked
        ? 'topic-row topic-blocked'
        : topic.needsAttention
          ? 'topic-row topic-attention'
          : isClosed(topic)
            ? 'topic-row topic-closed'
            : 'topic-row'
    }
  >
    <div className="topic-question">{topic.question}</div>
    <div className="topic-meta">
      <span className="topic-status">{topic.status.replace('_', ' ')}</span>
      <span className="topic-count">{topic.sources} sources</span>
      <span className="topic-count">{topic.findings} findings</span>
      {topic.openSubQuestions > 0 ? (
        <span className="topic-count">{topic.openSubQuestions} open</span>
      ) : null}
      <Button small className="topic-manage" onClick={onManage}>
        Manage
      </Button>
    </div>
    {topic.triggers.length > 0 ? (
      <ul className="topic-triggers">
        {topic.triggers.map((trigger) => (
          <li key={trigger} className="topic-trigger">
            {trigger}
          </li>
        ))}
      </ul>
    ) : null}
  </li>
)
