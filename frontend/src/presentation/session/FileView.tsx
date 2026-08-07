import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { useEffect, useState } from 'react'

import { useAttempts } from '@application/lesson/use-attempts.ts'
import { ApiError, errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { hasComponents, type ComponentAudience } from '@domain/lesson/document.ts'
import { humaniseEventType } from '@domain/session/event-kind.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { diffSubject, type FileRevision } from '@domain/workspace/workspace-file.ts'
import type { FilePath } from '@domain/shared/file-path.ts'
import type { SessionId } from '@domain/shared/identifier.ts'
import { classifyEventType } from '@domain/session/event-kind.ts'

import { CodeBlock, DiffView, Markdown } from '../common/content.tsx'
import { Chip, EmptyState, ErrorBox, Loading } from '../common/primitives.tsx'
import { clockTime, fullTime } from '../formatting/format.ts'
import { LessonDocument } from '../lesson/LessonDocument.tsx'

type Tab = 'content' | 'history'
type RenderMode = 'rendered' | 'source'

/** One file, read at the selected point — or its whole revision history. */
export const FileView = ({
  sessionId,
  path,
  scrub,
}: {
  sessionId: SessionId
  path: FilePath | null
  scrub: ScrubPoint
}) => {
  const [tab, setTab] = useState<Tab>('content')
  const [mode, setMode] = useState<RenderMode>('rendered')
  // Defaults to author because this console's reader is the person building the
  // course — the learner view is a preview of somebody else's screen.
  const [audience, setAudience] = useState<ComponentAudience>('author')

  // A different file is a different set of tabs' worth of state.
  useEffect(() => {
    setTab('content')
  }, [path?.value])

  if (!path) {
    return (
      <EmptyState
        title="No file selected."
        detail="Pick a file above to read it as of the selected event, or open its full revision history."
      />
    )
  }

  return (
    <>
      <div className="file-view-head">
        <span className="fv-path" title={path.value}>
          {path.value}
        </span>
        {path.isMarkdown && tab === 'content' ? (
          <div className="tabs">
            <TabButton active={mode === 'rendered'} onClick={() => setMode('rendered')}>
              rendered
            </TabButton>
            <TabButton active={mode === 'source'} onClick={() => setMode('source')}>
              source
            </TabButton>
          </div>
        ) : null}
        <AudienceTabs
          sessionId={sessionId}
          path={path}
          scrub={scrub}
          visible={path.isMarkdown && tab === 'content' && mode !== 'source'}
          audience={audience}
          onChange={setAudience}
        />
        <div className="tabs">
          <TabButton active={tab === 'content'} onClick={() => setTab('content')}>
            contents
          </TabButton>
          <TabButton active={tab === 'history'} onClick={() => setTab('history')}>
            history
          </TabButton>
        </div>
      </div>

      {tab === 'content' ? (
        <Contents
          sessionId={sessionId}
          path={path}
          scrub={scrub}
          mode={mode}
          audience={audience}
        />
      ) : (
        <History sessionId={sessionId} path={path} />
      )}
    </>
  )
}

const Contents = ({
  sessionId,
  path,
  scrub,
  mode,
  audience,
}: {
  sessionId: SessionId
  path: FilePath
  scrub: ScrubPoint
  mode: RenderMode
  audience: ComponentAudience
}) => {
  const { workspace, lessons } = useContainer()
  const attempts = useAttempts(sessionId, path, scrub)

  const contents = useQuery({
    queryKey: queryKeys.file(sessionId, path, scrub),
    queryFn: () => workspace.readFile(sessionId, path, scrub),
    // A 404 here is information, not a failure: the path had simply not been
    // written yet (or had been removed) at this point in the log. Retrying it
    // asks the same unchanging question again.
    retry: (count, error) => !(error instanceof ApiError && error.isNotFound) && count < 2,
    // The server folds the file to the scrub point for us, so a previous
    // point's contents stay up while a newer one is in flight rather than
    // flashing empty.
    placeholderData: (previous) => previous,
  })

  /** The parsed companion, fetched only for markdown.
   *
   * A second request rather than a replacement, because the source toggle and
   * every non-markdown file still need the raw bytes — and because a parse
   * failure must never cost the reader the file itself. On any error the viewer
   * falls back to rendering the markdown the way it always has, silently: an
   * error banner over a document that displays perfectly well would be noise. */
  const parsed = useQuery({
    queryKey: queryKeys.lesson(sessionId, path, audience, scrub),
    queryFn: () => lessons.parse(sessionId, path, audience, scrub),
    enabled: path.isMarkdown && mode === 'rendered',
    retry: false,
  })

  if (contents.isError) {
    const error = contents.error
    if (error instanceof ApiError && error.isNotFound) {
      return (
        <EmptyState
          title={ScrubPoint.isHistorical(scrub) ? 'Not in the workspace here.' : 'No such file.'}
          detail={
            ScrubPoint.isHistorical(scrub)
              ? `${path.value} did not exist at event ${scrub.at}.`
              : `${path.value} is not in the workspace at HEAD.`
          }
        />
      )
    }
    return (
      <ErrorBox
        title="Could not read this file"
        message={errorMessage(error)}
        onRetry={() => void contents.refetch()}
      />
    )
  }

  if (contents.data === undefined) return <Loading what="file" />

  const stale = contents.isPlaceholderData
  const rendered = path.isMarkdown && mode === 'rendered'

  // The parsed document wins when it has components to show; a markdown file
  // without any renders through the path it always did, which keeps the common
  // case free of a second render tree.
  if (rendered && hasComponents(parsed.data ?? null)) {
    return (
      <div className={clsx(stale && 'stale')}>
        <LessonDocument doc={parsed.data!} attempts={attempts} />
      </div>
    )
  }

  return rendered ? (
    <Markdown source={contents.data} className={clsx(stale && 'stale')} />
  ) : (
    <CodeBlock text={contents.data} className={clsx(stale && 'stale')} />
  )
}

/** Author or learner.
 *
 * Only shown for a document that actually has components: a view switch on a
 * file with nothing to withhold is a control that does nothing, and the header
 * is already crowded. Switching refetches rather than filters, because which
 * fields exist is the server's decision — that is the whole point of doing the
 * projection there — and the client has no key to hide even if it tried. */
const AudienceTabs = ({
  sessionId,
  path,
  scrub,
  visible,
  audience,
  onChange,
}: {
  sessionId: SessionId
  path: FilePath
  scrub: ScrubPoint
  visible: boolean
  audience: ComponentAudience
  onChange: (audience: ComponentAudience) => void
}) => {
  const { lessons } = useContainer()
  const parsed = useQuery({
    queryKey: queryKeys.lesson(sessionId, path, audience, scrub),
    queryFn: () => lessons.parse(sessionId, path, audience, scrub),
    enabled: visible,
    retry: false,
  })

  if (!visible || !hasComponents(parsed.data ?? null)) return null

  return (
    <div className="tabs">
      <TabButton
        active={audience === 'author'}
        title="Everything the file contains, including answers and authoring warnings."
        onClick={() => onChange('author')}
      >
        author
      </TabButton>
      <TabButton
        active={audience === 'learner'}
        title="Preview what a learner is sent: answers and rationales withheld, and graded on the server."
        onClick={() => onChange('learner')}
      >
        learner
      </TabButton>
    </div>
  )
}

const History = ({ sessionId, path }: { sessionId: SessionId; path: FilePath }) => {
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
        title="Could not read this file"
        message={errorMessage(history.error)}
        onRetry={() => void history.refetch()}
      />
    )
  }
  if (history.data.length === 0) {
    return (
      <EmptyState title="No recorded revisions." detail="Nothing in the log touched this path." />
    )
  }

  return (
    <>
      {history.data.map((revision, index) => (
        <Revision
          key={revision.index}
          revision={revision}
          previous={index > 0 ? history.data[index - 1]! : null}
          open={!closed.has(index)}
          onToggle={() =>
            setClosed((current) => {
              const next = new Set(current)
              if (next.has(index)) next.delete(index)
              else next.add(index)
              return next
            })
          }
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
      <div className="rev-head" onClick={onToggle}>
        <span>{open ? '▾' : '▸'}</span>
        <span className="rev-idx">#{revision.index}</span>
        <span className="rev-type">{humaniseEventType(revision.type)}</span>
        {revision.replaceAll ? <Chip>replace_all</Chip> : null}
        <span className="rev-time" title={fullTime(revision.occurredAt)}>
          {clockTime(revision.occurredAt)}
        </span>
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

const TabButton = ({
  active,
  title,
  onClick,
  children,
}: {
  active: boolean
  title?: string
  onClick: () => void
  children: React.ReactNode
}) => (
  <button
    type="button"
    className={clsx('tab', active && 'active')}
    title={title}
    onClick={() => {
      if (!active) onClick()
    }}
  >
    {children}
  </button>
)
