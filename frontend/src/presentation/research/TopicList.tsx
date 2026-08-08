import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { byUrgency, isClosed, type TopicView } from '@domain/research/topic.ts'
import type { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import { Button, EmptyState, ErrorBox, Loading } from '../common/primitives.tsx'
import { TopicStatusDialog } from './TopicStatusDialog.tsx'

/** The project's topic queue, ranked by `byUrgency`: blocked topics first,
 *  then ones flagged for attention, then everything still live, then
 *  everything closed.
 *
 * A plain query rather than a poll — unlike `Workers`, nothing here is
 * expected to move within the span of one page view, so there is no
 * `refetchInterval` to keep a stale badge honest. A manual action (task 6)
 * is what invalidates this cache.
 */
export const TopicList = ({ projectId }: { projectId: ProjectId }) => {
  const { topics } = useContainer()
  // The id of the topic being managed, not its detail: the detail is fetched
  // fresh (below) rather than reused from the list row, because the row's
  // `TopicView` leaves out the rationale, scope and sub-questions the dialog
  // needs and `TopicDetail` is what `TopicStatusDialog` was built to take.
  const [managing, setManaging] = useState<TopicId | null>(null)

  const query = useQuery({
    queryKey: queryKeys.topics(projectId),
    queryFn: () => topics.list(projectId),
  })

  const detail = useQuery({
    queryKey: managing ? queryKeys.topic(projectId, managing) : ['topic', 'none'],
    queryFn: () => topics.read(projectId, managing!),
    enabled: managing !== null,
  })

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

  const ranked = [...query.data].sort(byUrgency)

  return (
    <>
      <ul className="topic-list">
        {ranked.map((topic) => (
          <TopicRow key={topic.topicId} topic={topic} onManage={() => setManaging(topic.topicId)} />
        ))}
      </ul>
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
    </>
  )
}

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
