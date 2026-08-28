import type { ReactNode } from 'react'

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
  toolbar,
}: {
  projectId: ProjectId
  /** Passed straight through to `TopicQueue`'s toolbar line. Threaded rather
   *  than rendered here because the controls on it are the *project page's* --
   *  `QueueHeader` lives under `presentation/project`, and a container in
   *  `presentation/research` reaching up into it would point the dependency
   *  between the two directories backwards. `ProjectView` owns both. */
  toolbar?: ReactNode
  /** Which topic is open, owned by the route. Defaulted so the queue can still
   *  be rendered outside a routed page -- see `useTopicQueue`. */
  open?: TopicId | null
  onOpen?: (topicId: TopicId | null) => void
}) => {
  const { query, detail, managing, onCloseManage, queue } = useTopicQueue(projectId, open, onOpen)

  // The toolbar outlives both fetch states, and that is not tidiness.
  //
  // It carries the only two inbound links to `#/p/<id>/ask` and
  // `#/p/<id>/dialogue`, and both branches below return *instead of* the
  // queue -- so threading it only into `TopicQueue` took both doors away for
  // the length of every topic request, and away entirely on a project whose
  // topic read fails. That is the one-way door this pane has now shipped
  // twice, arriving a third time through a state rather than through a
  // deletion. Caught by `App.test.tsx`, whose container has no `topics.list`
  // at all and therefore renders the error branch.
  //
  // Duplicated placement rather than a shared wrapper: on the happy path it
  // belongs *on the search box's line*, which only `TopicQueue` draws, and a
  // wrapper that owned the line would have to own the search box with it.
  if (query.isPending) {
    return (
      <>
        <ToolbarLine>{toolbar}</ToolbarLine>
        <Loading what="topics" />
      </>
    )
  }

  if (query.isError) {
    return (
      <>
        <ToolbarLine>{toolbar}</ToolbarLine>
        <ErrorBox
          heading="Could not read this project's topics"
          message={query.error instanceof Error ? query.error.message : String(query.error)}
          onRetry={() => void query.refetch()}
        />
      </>
    )
  }

  return (
    <>
      <TopicQueue {...queue} toolbar={toolbar} />
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

/** The toolbar with no search box beside it, for the two states that have no
 *  queue. Right-aligned so the controls sit where they sit on the line they
 *  normally share, rather than jumping to the left margin and back when the
 *  topics arrive. */
const ToolbarLine = ({ children }: { children: ReactNode }) =>
  children === undefined ? null : <div className="flex justify-end">{children}</div>
