import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { summariesAsForest } from '@infrastructure/http/mappers.ts'
import type { ForkNode } from '@domain/session/session.ts'
import { shortId } from '@domain/shared/identifier.ts'
import { truncate } from '@domain/conversation/message.ts'
import { errorMessage } from '@application/ports/errors.ts'

import { Chip, EmptyState, ErrorBox, Loading } from '../common/primitives.tsx'
import { fullTime, plural, relativeTime } from '../formatting/format.ts'
import { sessionHref } from '../routing/routes.ts'
import { navigate } from '../routing/use-route.ts'

/** Every session, as the fork tree it actually is.
 *
 * Two sources, deliberately. `/api/tree` is the shape; `/api/sessions` is the
 * per-row detail *and* the fallback — if the tree projection has drifted and
 * answers empty while sessions plainly exist, the flat list is rendered
 * instead. A truthful degradation beats a "no sessions yet" that is a lie.
 */
export const SessionTree = () => {
  const { sessions } = useContainer()

  const tree = useQuery({
    queryKey: queryKeys.tree(),
    queryFn: () => sessions.tree(),
  })
  const list = useQuery({
    queryKey: queryKeys.sessions(),
    queryFn: () => sessions.list(),
  })

  if (tree.isPending) return <Loading what="sessions" />
  if (tree.isError) {
    return (
      <ErrorBox
        title="Could not load the session tree"
        message={errorMessage(tree.error)}
        onRetry={() => void tree.refetch()}
      />
    )
  }

  const summaries = list.data ?? []
  const roots =
    tree.data.length > 0 ? tree.data : summaries.length > 0 ? summariesAsForest(summaries) : []

  if (roots.length === 0) {
    return (
      <EmptyState
        title="No sessions yet."
        detail="Create one to start an event log, or run the CLI (uv run main.py) — sessions are shared."
      />
    )
  }

  const detail = new Map(summaries.map((summary) => [summary.id, summary]))
  return <TreeLevel nodes={roots} depth={0} detail={detail} />
}

const TreeLevel = ({
  nodes,
  depth,
  detail,
}: {
  nodes: readonly ForkNode[]
  depth: number
  detail: Map<string, { turns: number | null; files: number | null; startedAt: string | null }>
}) => (
  <ul className={depth === 0 ? 'tree' : undefined}>
    {nodes.map((node) => (
      <li key={node.id}>
        <SessionNode node={node} detail={detail} />
        {node.children.length > 0 ? (
          <TreeLevel nodes={node.children} depth={depth + 1} detail={detail} />
        ) : null}
      </li>
    ))}
  </ul>
)

/** A row's numbers come from whichever source has them.
 *
 * The tree and the list are two projections of the same session and either can
 * be the one that is current; taking the first that answers keeps a row from
 * reading "0 turns" purely because the endpoint that knew was the other one. */
const pick = (a: number | null | undefined, b: number | null | undefined): number | null =>
  typeof a === 'number' ? a : typeof b === 'number' ? b : null

const SessionNode = ({
  node,
  detail,
}: {
  node: ForkNode
  detail: Map<string, { turns: number | null; files: number | null; startedAt: string | null }>
}) => {
  const extra = detail.get(node.id)
  const failed = pick(node.failedTurns, null)
  const startedAt = node.startedAt ?? extra?.startedAt ?? null

  return (
    <button type="button" className="node" onClick={() => navigate(sessionHref(node.id))}>
      <div className="node-top">
        <span className="node-id">{shortId(node.id)}</span>
        <span className={node.firstMessage ? 'node-msg' : 'node-msg empty'}>
          {node.firstMessage ? truncate(node.firstMessage, 120) : 'no messages yet'}
        </span>
        {node.forkedAt !== null ? <Chip tone="fork">forked @ event {node.forkedAt}</Chip> : null}
        {failed ? <Chip tone="fail">{plural(failed, 'failed turn')}</Chip> : null}
      </div>
      <div className="node-stats">
        <span>
          <b>{pick(node.turns, extra?.turns) ?? 0}</b> turns
        </span>
        <span>
          <b>{pick(node.files, extra?.files) ?? 0}</b> files
        </span>
        <span title={fullTime(startedAt)}>{relativeTime(startedAt)}</span>
      </div>
    </button>
  )
}
