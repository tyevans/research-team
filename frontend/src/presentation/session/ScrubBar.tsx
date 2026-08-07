import clsx from 'clsx'

import { humaniseEventType } from '@domain/session/event-kind.ts'
import { entryAt, type LogEntry } from '@domain/session/log-entry.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { totalEvents, type SessionProjection } from '@domain/session/session.ts'
import { truncate } from '@domain/conversation/message.ts'
import { shortId } from '@domain/shared/identifier.ts'

import { Button, Chip } from '../common/primitives.tsx'
import { plural } from '../formatting/format.ts'

interface ScrubBarProps {
  head: SessionProjection | null
  log: readonly LogEntry[]
  scrub: ScrubPoint
  loading: boolean
  onSelect: (at: ScrubPoint) => void
  onFork: () => void
  onEndSession: () => void
}

/** Where the view is anchored, and what can be done from there.
 *
 * "live · head" and "time travel" are different states rather than different
 * numbers, because the difference is what a reader needs to know first: at
 * HEAD the log grows underneath you, and scrubbed it does not. */
export const ScrubBar = ({
  head,
  log,
  scrub,
  loading,
  onSelect,
  onFork,
  onEndSession,
}: ScrubBarProps) => {
  const historical = ScrubPoint.isHistorical(scrub)
  const total = totalEvents(head?.eventCount, log.length)

  return (
    <div className={clsx('scrub-bar', historical && 'historical')}>
      {historical ? (
        <>
          <span className="scrub-state hist">
            <span className="conn-dot" style={{ background: 'var(--accent)' }} />
            time travel
          </span>
          <span className="scrub-detail">
            {describeHistorical(entryAt(log, scrub.at), scrub.at, total, loading)}
          </span>
        </>
      ) : (
        <>
          <span className="scrub-state live">
            <span className="conn-dot" style={{ background: 'var(--k-file)' }} />
            live · head
          </span>
          <span className="scrub-detail">{describeHead(head, total)}</span>
        </>
      )}

      <ProjectChips head={head} />

      <div className="scrub-actions">
        {/* Ending a session is the other half of joining a project, and the only
            way work done here reaches the next one: releasing advances the
            project's tip. Named for the thing the user is trying to do; the
            lease is an implementation detail of it. */}
        {!historical && head?.projectId && head.holdsProject ? (
          <Button
            small
            title="Hand this session's files back to the project and stop working here"
            onClick={onEndSession}
          >
            End session
          </Button>
        ) : null}
        {historical ? (
          <>
            <Button small onClick={onFork}>
              Fork here
            </Button>
            <Button small tone="accent" onClick={() => onSelect(ScrubPoint.head())}>
              Back to live
            </Button>
          </>
        ) : null}
      </div>
    </div>
  )
}

const describeHead = (head: SessionProjection | null, total: number): string =>
  [
    plural(total, 'event'),
    plural(head?.turnIndex ?? 0, 'turn'),
    plural(head?.files.length ?? 0, 'file'),
    head?.modelName,
    head?.failedTurns ? plural(head.failedTurns, 'failed turn') : null,
  ]
    .filter(Boolean)
    .join(' · ')

const describeHistorical = (
  entry: LogEntry | null,
  at: number,
  total: number,
  loading: boolean,
): string => {
  const what = entry
    ? ` — ${humaniseEventType(entry.type)}${entry.summary ? `: ${truncate(entry.summary, 90)}` : ''}`
    : ''
  return `viewing the workspace as of event ${at} of ${total}${what}${loading ? '  …folding' : ''}`
}

/** Project state belongs on this bar because it changes what typing into this
 *  session *means*: whether the work lands somewhere the next session will see,
 *  and whether the agent can reach the graph its prompt promises. */
const ProjectChips = ({ head }: { head: SessionProjection | null }) => {
  if (!head?.projectId) return null
  const attached = head.knowledgeAttached
  return (
    <span
      className={clsx('scrub-project', !head.holdsProject && 'stale-hold')}
      title={
        head.holdsProject
          ? 'This session holds the project. End it to pass its files on.'
          : 'Another session has taken this project over; work here no longer reaches it.'
      }
    >
      <Chip>project {shortId(head.projectId)}</Chip>
      <Chip
        tone={attached ? 'ok' : 'warn'}
        title={
          attached
            ? 'The knowledge graph is attached; remember/graph_search are available.'
            : 'No knowledge graph attached — the agent has no remember/graph_search here.'
        }
      >
        {attached ? 'graph on' : 'graph off'}
      </Chip>
      {head.holdsProject ? null : <Chip tone="warn">not held</Chip>}
    </span>
  )
}
