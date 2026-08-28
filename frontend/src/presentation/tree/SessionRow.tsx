import type { ForkNode, SessionSummary } from '@domain/session/session.ts'
import { shortId } from '@domain/shared/identifier.ts'
import { truncate } from '@domain/conversation/message.ts'

import { Chip } from '../common/primitives.tsx'
import { plural, relativeTime } from '../formatting/format.ts'
import { sessionHref } from '../routing/routes.ts'
import { navigate } from '../routing/use-route.ts'

/** One session, led by the only field a human wrote.
 *
 * The inverse of what this row used to be. The id came first and in the
 * page's single accent colour, so the eye was pulled to a hex string dozens of
 * times per screen while the first message — the thing anyone is actually
 * scanning for — sat beside it, truncated and clipped by whatever width the
 * chips left. The message is the headline now and the id is trailing metadata,
 * which is what it is.
 */
/** **The `held` chip is gone, and so is the `heldBy` that fed it.** It marked
 *  the session holding the project — which, on the landing page, was almost
 *  always the row it was drawn on, because `currentSession` prefers the holder
 *  when choosing what to preview. So the chip told a reader that the one
 *  session they were being shown was the one being shown, in the vocabulary of
 *  lock ownership. Which session holds a project decides where the next write
 *  goes; it is not a property of the session worth a chip on an index.
 *
 *  Nothing else read the prop: `SessionForest` took `heldBy` only to pass it
 *  down, and `ProjectList` was the only caller of either. The fact itself is
 *  untouched on `Project.activeSessionId`, where the preview choice and the
 *  delete call still read it. */
export const SessionRow = ({ session }: { session: SessionSummary }) => (
  <button type="button" className="row" onClick={() => navigate(sessionHref(session.id))}>
    <div className="row-head">
      <span className={session.firstMessage ? 'row-title' : 'row-title row-title-empty'}>
        {session.firstMessage ? truncate(session.firstMessage, 120) : 'no messages yet'}
      </span>
      {session.forkedAt !== null ? <Chip tone="fork">forked @ {session.forkedAt}</Chip> : null}
      {session.failedTurns ? (
        <Chip tone="fail">{plural(session.failedTurns, 'failed turn')}</Chip>
      ) : null}
      <span className="row-id">{shortId(session.id)}</span>
    </div>
    <div className="row-stats">
      <span>
        <b>{session.turns ?? 0}</b> turns
      </span>
      <span>
        <b>{session.files ?? 0}</b> files
      </span>
      <span>{relativeTime(session.startedAt)}</span>
    </div>
  </button>
)

/** A project's sessions, keeping the lineage that is the product.
 *
 * Nesting survives here and nowhere else on this page: inside one project it
 * is a relationship between a handful of rows a reader can take in, where at
 * the top of the document it was the structure of everything and put this
 * morning's fork under a parent from March.
 */
export const SessionForest = ({
  nodes,
  depth = 0,
}: {
  nodes: readonly ForkNode[]
  depth?: number
}) => (
  <ul className={depth === 0 ? 'tree' : undefined}>
    {nodes.map((node) => (
      <li key={node.id}>
        <SessionRow session={node} />
        {node.children.length > 0 ? (
          <SessionForest nodes={node.children} depth={depth + 1} />
        ) : null}
      </li>
    ))}
  </ul>
)
