import { isBusy, nest, type Roster, type WorkerNode } from '@domain/worker/worker.ts'
import { shortId, type SessionId } from '@domain/shared/identifier.ts'

import { Chip } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'

/** What is running on a project, drawn from a roster somebody else fetched.
 *
 * Split out of `Workers`, which now does nothing but poll and hand the result
 * here. The reason is that the states worth looking at are exactly the ones a
 * container makes hard to reach: a roster that is stale, a stale roster that
 * is *also* empty, and a first poll that failed with nothing behind it. Each
 * needed a fake repository and a query invalidation to see; each is now a
 * story and a prop.
 *
 * The one rule this must not break, inherited from the component it came out
 * of: **a failed poll keeps the last roster and marks it stale.** Rendering
 * empty would say "nothing is running", which is the specific lie this panel
 * exists to kill -- so `roster` and `stale` are separate props rather than one
 * nullable roster, and `stale` with a roster present is a legal, meaningful
 * combination rather than an inconsistency.
 */
export const WorkerList = ({
  roster,
  stale = false,
  watching,
  onWatch,
}: {
  /** The last roster that arrived, or `null` if none ever has. */
  roster: Roster | null
  /** The most recent poll failed. With a roster, this marks it as possibly
   *  out of date; with `roster` null, the caller should be rendering
   *  `WorkerListUnavailable` instead -- there is nothing to qualify. */
  stale?: boolean
  watching: SessionId | null
  onWatch: (sessionId: SessionId | null) => void
}) => (
  <>
    <div className="worker-head">
      <h3 className="worker-title">Working now</h3>
      {isBusy(roster) ? <Chip tone="current">{roster!.workers.length} running</Chip> : null}
      {stale ? (
        <Tooltip explanation="The last poll failed; this is the last roster that arrived">
          <Chip tone="run-short">stale</Chip>
        </Tooltip>
      ) : !isBusy(roster) ? (
        <Chip>idle</Chip>
      ) : null}
    </div>

    {roster && roster.workers.length > 0 ? (
      <ul className="worker-list">
        {nest(roster.workers).map((node) => (
          <Row key={node.worker.ref} node={node} watching={watching} onWatch={onWatch} />
        ))}
      </ul>
    ) : stale ? (
      // Stale and empty must not read as "nothing is running": that is a
      // present-tense claim this render cannot back up, since the only thing
      // known is what the last roster (also empty) said, not what is true now.
      // Say only what is actually known.
      <p className="sub worker-sub">
        The last poll failed. As of the last roster that arrived, nothing was running.
      </p>
    ) : (
      <p className="sub worker-sub">
        Nothing is running on this project.{' '}
        {roster && roster.idleSessionIds.length > 0
          ? `${roster.idleSessionIds.length} session(s) attached and quiet.`
          : 'No sessions are attached.'}
      </p>
    )}
  </>
)

/** No roster has ever arrived, and the last attempt failed.
 *
 * Its own component rather than a branch inside `WorkerList`, because it is
 * the one case with nothing to say about workers at all -- there is no head,
 * no chip and no list, and threading a `roster: null, failed: true` pair
 * through the component above would mean every branch in it guarding against
 * a state it never renders.
 */
export const WorkerListUnavailable = () => (
  <p className="sub worker-sub">
    Could not read what is running on this project. This build may not expose the roster.
  </p>
)

const Row = ({
  node,
  watching,
  onWatch,
  nested = false,
}: {
  node: WorkerNode
  watching: SessionId | null
  onWatch: (sessionId: SessionId | null) => void
  nested?: boolean
}) => {
  const { worker } = node
  // A worker with a session gets a button that opens it. Extraction has no
  // session of its own — its detail view is the extraction pane — so it
  // renders as text rather than a dead button.
  const target = worker.sessionId

  return (
    <>
      <li className={nested ? 'worker-row worker-child' : 'worker-row'}>
        <span className={`worker-dot worker-dot-${worker.kind}`} aria-hidden="true" />
        <span className="worker-kind">{worker.kind}</span>
        {target ? (
          <button
            type="button"
            className="btn btn-sm worker-open"
            aria-pressed={watching === target}
            onClick={() => onWatch(watching === target ? null : target)}
          >
            {worker.detail}
          </button>
        ) : (
          <span className="worker-detail">{worker.detail}</span>
        )}
        {target ? <span className="muted worker-ref">{shortId(target)}</span> : null}
      </li>
      {node.children.map((child) => (
        <Row key={child.worker.ref} node={child} watching={watching} onWatch={onWatch} nested />
      ))}
    </>
  )
}
