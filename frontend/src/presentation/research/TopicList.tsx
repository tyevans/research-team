import type { ProjectId } from '@domain/shared/identifier.ts'

import { ErrorBox, Loading } from '../common/primitives.tsx'
import { TopicQueue } from './TopicQueue.tsx'
import { TopicStatusDialog } from './TopicStatusDialog.tsx'
import { useTopicQueue } from './use-topic-queue.ts'

/** The project's topic queue, ranked by `byUrgency`: blocked topics first,
 *  then ones flagged for attention, then everything still live, then
 *  everything closed.
 *
 * A container and nothing else. It owns the two states that are about the
 * *fetch* rather than about the queue -- "still loading" and "the read
 * failed" -- and hands everything else to `TopicQueue`, which cannot fetch.
 * "The queue is empty" is not one of them: an empty queue is a fact about the
 * project that the queue's own markup renders, which is what lets a story show
 * it.
 */
export const TopicList = ({ projectId }: { projectId: ProjectId }) => {
  const { query, detail, managing, onCloseManage, queue } = useTopicQueue(projectId)

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

  return (
    <>
      <TopicQueue {...queue} />
      {/* Rendered only once the detail has actually loaded -- opening on the
          click and closing the moment `read` resolves would flash a dialog
          with nothing in it, and `TopicStatusDialog` requires a `TopicDetail`
          to render at all. */}
      {managing && detail.data ? (
        <TopicStatusDialog projectId={projectId} topic={detail.data} onClose={onCloseManage} />
      ) : null}
    </>
  )
}
