import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { queryKeys } from '@application/queries/keys.ts'
import {
  useCancelDispatch,
  useDispatchBoard,
  useDispatchTopic,
} from '@application/research/use-dispatch.ts'
import { useContainer } from '@app/container-context.tsx'
import type { Dispatch } from '@domain/research/dispatch.ts'
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

  // Read unconditionally rather than only when something is running: the
  // point of the catch-up route is a tab that arrived *after* a dispatch
  // started, which cannot be detected without asking.
  const dispatches = useDispatchBoard(projectId)
  const dispatching = useDispatchTopic(projectId)
  const cancelling = useCancelDispatch(projectId)

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

      {/* The aggregate, so a reader who scrolled away from the running row
          still knows something is going. One stop control here rather than a
          cancel per queued row, because cancel is per project on the server
          and a per-row control would offer an action it cannot honour. */}
      {dispatches.running || dispatches.queuedCount > 0 ? (
        <div className="topic-dispatch-bar">
          <span>
            {dispatches.running ? '1 running' : 'none running'}
            {dispatches.queuedCount > 0 ? `, ${dispatches.queuedCount} queued` : ''}
          </span>
          <Button
            small
            disabled={cancelling.isPending}
            onClick={() => cancelling.mutate()}
            title="Stop the running dispatch and drop everything queued"
          >
            Stop
          </Button>
        </div>
      ) : null}

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
              dispatch={dispatches.byTopic.get(topic.topicId)}
              isDispatching={dispatching.isPending}
              onManage={() => setManaging(topic.topicId)}
              onDispatch={() =>
                dispatching.mutate({ topicId: topic.topicId, action: 'understanding' })
              }
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

/** Nothing has been gathered for this topic yet.
 *
 * The one thing in this feature that disables a control, and it is worth it:
 * synthesising a topic with no sources and no findings produces the model's
 * own prior knowledge presented as project findings, which is confabulation
 * that looks like a deliverable. Research is the action that fixes it, and
 * research is not built yet — so the button says why rather than offering a
 * next step it cannot take.
 */
const hasNothingToSynthesise = (topic: TopicView): boolean =>
  topic.sources === 0 && topic.findings === 0

/** `1st`, `2nd`, `3rd`, `4th`. Small enough that a dependency would be absurd,
 *  and the bundle budget has 0.6 kB of headroom on `graph-` anyway. */
const ordinal = (position: number): string => {
  const tens = position % 100
  if (tens >= 11 && tens <= 13) return `${position}th`
  const suffix = ['th', 'st', 'nd', 'rd'][position % 10] ?? 'th'
  return `${position}${suffix}`
}

/** What one dispatch reads as on the row that produced it.
 *
 * Kept for finished dispatches rather than cleared, deliberately: a chip that
 * vanishes on the next render is how a reader concludes the button did
 * nothing. A failure in particular has to persist, because the failure and
 * the retry are the same row.
 */
const DispatchChip = ({ dispatch }: { dispatch: Dispatch }) => {
  if (dispatch.status === 'queued') {
    return (
      <span className="topic-dispatch topic-dispatch-queued">
        ⧗ queued · {dispatch.position === null ? 'waiting' : ordinal(dispatch.position)}
      </span>
    )
  }
  if (dispatch.status === 'running') {
    return (
      <span className="topic-dispatch topic-dispatch-running">⟳ {dispatch.action} · running</span>
    )
  }
  if (dispatch.status === 'failed') {
    return (
      // `title` carries the untruncated text: the chip is clamped to one line
      // in a 320px rail, and a model's error can be a paragraph.
      <span className="topic-dispatch topic-dispatch-failed" title={dispatch.detail ?? undefined}>
        ✕ {dispatch.action} · failed · {dispatch.detail ?? 'no reason given'}
      </span>
    )
  }
  if (dispatch.status === 'cancelled') {
    return <span className="topic-dispatch">⊘ {dispatch.action} · cancelled</span>
  }
  return (
    <span className="topic-dispatch topic-dispatch-done">
      ✓ {dispatch.action} · {dispatch.path ?? 'written'}
    </span>
  )
}

const TopicRow = ({
  topic,
  dispatch,
  onManage,
  onDispatch,
  isDispatching,
}: {
  topic: TopicView
  dispatch: Dispatch | undefined
  onManage: () => void
  onDispatch: () => void
  isDispatching: boolean
}) => {
  const empty = hasNothingToSynthesise(topic)
  return (
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
        {/* One button rather than the split control the design sketches: with
            one action there is nothing to split, and a menu holding a single
            item is a click in front of a button. It becomes a split button
            when `research` and `lesson` land. */}
        <Button
          small
          className="topic-dispatch-button"
          disabled={empty || isDispatching || dispatch?.status === 'queued'}
          title={
            empty
              ? 'Nothing gathered for this topic yet'
              : 'Write down what this project understands about this topic'
          }
          onClick={onDispatch}
        >
          Write understanding
        </Button>
        <Button small className="topic-manage" onClick={onManage}>
          Manage
        </Button>
      </div>
      {dispatch ? <DispatchChip dispatch={dispatch} /> : null}
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
}
