import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { byUrgency, isClosed, type TopicView } from '@domain/research/topic.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { EmptyState, ErrorBox, Loading } from '../common/primitives.tsx'

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

  const query = useQuery({
    queryKey: queryKeys.topics(projectId),
    queryFn: () => topics.list(projectId),
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
    <ul className="topic-list">
      {ranked.map((topic) => (
        <TopicRow key={topic.topicId} topic={topic} />
      ))}
    </ul>
  )
}

const TopicRow = ({ topic }: { topic: TopicView }) => (
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
