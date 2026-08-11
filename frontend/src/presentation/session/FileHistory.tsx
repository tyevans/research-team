import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { classifyEventType, humaniseEventType } from '@domain/session/event-kind.ts'
import { diffSubject, type FileRevision } from '@domain/workspace/workspace-file.ts'
import type { FilePath } from '@domain/shared/file-path.ts'
import type { SessionId } from '@domain/shared/identifier.ts'

import { DiffView } from '../common/content.tsx'
import { Chip, EmptyState, ErrorBox, Loading } from '../common/primitives.tsx'
import { clockTime } from '../formatting/format.ts'

/** Every recorded change to one path, oldest first.
 *
 * The whole log for the path, not a fold to the scrub point: a revision list
 * that stopped where the reader is standing would hide the very edits they
 * scrubbed back to understand. */
export const FileHistory = ({ sessionId, path }: { sessionId: SessionId; path: FilePath }) => {
  const { workspace } = useContainer()
  const [closed, setClosed] = useState<ReadonlySet<number>>(new Set())

  const history = useQuery({
    queryKey: queryKeys.fileHistory(sessionId, path),
    queryFn: () => workspace.history(sessionId, path),
  })

  if (history.isPending) return <Loading what="history" />
  if (history.isError) {
    return (
      <ErrorBox
        heading="Could not read this file"
        message={errorMessage(history.error)}
        onRetry={() => void history.refetch()}
      />
    )
  }
  if (history.data.length === 0) {
    return (
      <EmptyState heading="No recorded revisions." detail="Nothing in the log touched this path." />
    )
  }

  const toggle = (index: number) =>
    setClosed((current) => {
      const next = new Set(current)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })

  return (
    <>
      {history.data.map((revision, index) => (
        <Revision
          key={revision.index}
          revision={revision}
          previous={index > 0 ? history.data[index - 1]! : null}
          // Expanded by default: a revision list nobody opens is a list of
          // timestamps, and the diff is the thing worth reading.
          open={!closed.has(index)}
          onToggle={() => toggle(index)}
        />
      ))}
    </>
  )
}

const Revision = ({
  revision,
  previous,
  open,
  onToggle,
}: {
  revision: FileRevision
  previous: FileRevision | null
  open: boolean
  onToggle: () => void
}) => {
  const subject = diffSubject(revision, previous)
  return (
    <div className={`rev k-${classifyEventType(revision.type)}`}>
      {/* A real control rather than a clickable div. `jsx-a11y` found this on
          the day it was installed and it is a genuine defect, not a false
          positive: before this, the revision header could be opened with a
          mouse and by no other means -- no role, no tab stop, no key handler
          -- so the diff underneath it was unreachable for a keyboard user.

          Deliberately `role="button"` on the existing div rather than a real
          `<button>`: the header is a grid of five spans and a chip, and a
          button element brings its own display, font and padding that would
          have to be reset, which is a visual change in a phase that promises
          none. The cost of that choice is that the Enter/Space handling below
          is ours to get right, where a `<button>` would have brought it for
          free -- `FileHistory.test.tsx` is what fails if it regresses. Phase 2
          replaces the whole thing with `Disclosure` on Radix and this goes
          away. */}
      <div
        className="rev-head"
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={onToggle}
        onKeyDown={(event) => {
          // Space scrolls the page by default, which is the wrong answer when
          // the thing under the cursor is a fold.
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            onToggle()
          }
        }}
      >
        <span>{open ? '▾' : '▸'}</span>
        <span className="rev-idx">#{revision.index}</span>
        <span className="rev-type">{humaniseEventType(revision.type)}</span>
        {revision.replaceAll ? <Chip>replace_all</Chip> : null}
        {/* The full timestamp used to hang off this as a `title`. It is gone
            rather than converted: `.rev-head` is itself `role="button"`, so a
            `Tooltip` here would put one interactive element inside another,
            and the date the clock time omits is on every one of these rows in
            the timeline beside it. */}
        <span className="rev-time">{clockTime(revision.occurredAt)}</span>
      </div>
      {open ? (
        <div className="rev-body">
          {subject.note ? <div className="rev-note">{subject.note}</div> : null}
          <DiffView before={subject.before} after={subject.after} />
        </div>
      ) : null}
    </div>
  )
}
