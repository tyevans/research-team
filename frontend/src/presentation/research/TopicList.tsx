import type { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import { ErrorBox, Loading } from '../common/primitives.tsx'
import { TopicQueue } from './TopicQueue.tsx'
import { TopicManagePane } from './TopicManagePane.tsx'
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
export const TopicList = ({
  projectId,
  open = null,
  onOpen,
}: {
  projectId: ProjectId
  /** Which topic is open, owned by the route. Defaulted so the queue can still
   *  be rendered outside a routed page -- see `useTopicQueue`. */
  open?: TopicId | null
  onOpen?: (topicId: TopicId | null) => void
}) => {
  const { query, detail, managing, onCloseManage, queue } = useTopicQueue(projectId, open, onOpen)

  if (query.isPending) return <Loading what="topics" />

  if (query.isError) {
    return (
      <ErrorBox
        heading="Could not read this project's topics"
        message={query.error instanceof Error ? query.error.message : String(query.error)}
        onRetry={() => void query.refetch()}
      />
    )
  }

  return (
    <>
      <TopicQueue {...queue} />
      {/* The wait is the same one the drawer needed and the reason has
          changed: `TopicManagePane` requires a `TopicDetail` to render at
          all, and while it was an overlay, opening on the click would have
          flashed an empty panel over the page. It is a region in the column
          now, so what a premature mount would cost is the queue jumping down
          the page and back -- a different symptom of the same missing read.

          `Loading` rather than nothing, which the drawer did not need and this
          does: a route-opened topic arrives with no click behind it, so with
          nothing rendered a reader following a link would see the plain queue
          for the length of a request and conclude the link had failed. That
          is exactly the defect this threading exists to fix, reintroduced one
          request later. */}
      {managing === null ? null : detail.data ? (
        <TopicManagePane projectId={projectId} topic={detail.data} onClose={onCloseManage} />
      ) : (
        <Loading what="topic" />
      )}
    </>
  )
}
