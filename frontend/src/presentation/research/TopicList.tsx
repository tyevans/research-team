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
  header,
}: {
  projectId: ProjectId
  /** Rendered above the queue, in both fetch states as well as the loaded one.
   *
   * A slot rather than a component, because what goes here is the *project
   * page's* -- `TopicsDrawer` lives under `presentation/project`, and a
   * container in `presentation/research` reaching up into it would point the
   * dependency between the two directories backwards.
   *
   *  **A function of the shown ids, and that signature is the safety
   *  property.** The slot holds "find sources for every topic shown", whose
   *  whole guarantee is that the number on the button and the number enqueued
   *  are the same by construction rather than by two pieces of code agreeing.
   *  The ids handed here are the very array the rows below are rendered from,
   *  so there is no second definition of "shown" to drift from the first --
   *  which is the reason the route refuses an "all" and makes the client name
   *  every id (`dispatch_topics` in `app.py`).
   *
   *  It is `[]` in both fetch states below, and that is honest rather than
   *  convenient: a queue that has not loaded is showing nothing, and the
   *  control reads "Find sources for 0 topics" and will not press. */
  header?: (shownTopicIds: readonly TopicId[]) => ReactNode
  /** Which topic is open, owned by the route. Defaulted so the queue can still
   *  be rendered outside a routed page -- see `useTopicQueue`. */
  open?: TopicId | null
  onOpen?: (topicId: TopicId | null) => void
}) => {
  const { query, detail, managing, onCloseManage, queue, shownTopicIds } = useTopicQueue(
    projectId,
    open,
    onOpen,
  )

  // The header outlives both fetch states, and that is not tidiness: it holds
  // the fan-out, whose control reports the scope it would act on, and a
  // control that vanished while the queue loaded would have a reader
  // concluding the drawer had nothing in it. Rendered identically in all
  // three branches rather than only in the loaded one, which is why it is a
  // slot and not something `TopicQueue` draws.
  if (query.isPending) {
    return (
      <>
        {header?.([])}
        <Loading what="topics" />
      </>
    )
  }

  if (query.isError) {
    return (
      <>
        {header?.([])}
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
      {header?.(shownTopicIds)}
      {/* The queue is the part that scrolls, so it is the part given the
          slack: `flex-auto` with `min-h-0` under a column parent, rather than
          `TopicQueue`'s own `h-full`, which would be 100% of a box the header
          above it is also using. */}
      <div className="flex min-h-0 flex-auto flex-col">
        <TopicQueue {...queue} />
      </div>
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
