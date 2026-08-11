import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { useCallback, useState } from 'react'

import { useAttempts } from '@application/lesson/use-attempts.ts'
import { useLesson, type Lesson } from '@application/lesson/use-lesson.ts'
import { ApiError, errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { ComponentAudience } from '@domain/lesson/document.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { FilePath } from '@domain/shared/file-path.ts'
import type { SessionId } from '@domain/shared/identifier.ts'

import { CodeBlock, Markdown } from '../common/content.tsx'
import { EmptyState, ErrorBox, Loading } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
import { LessonDocument } from '../lesson/LessonDocument.tsx'
import { FileHistory } from './FileHistory.tsx'

type Tab = 'content' | 'history'
type RenderMode = 'rendered' | 'source'

/** One file, read at the selected point — or its whole revision history.
 *
 * The parse is fetched once, here, and handed down. Both things that need it —
 * the renderer and the author/learner toggle — are asking the same question of
 * the same document, and two queries could answer it differently for a frame.
 */
export const FileView = ({
  sessionId,
  path,
  scrub,
}: {
  sessionId: SessionId
  path: FilePath | null
  scrub: ScrubPoint
}) => {
  /** The open tab, stamped with the file it belongs to.
   *
   * A different file starts on its contents, not on whatever tab the last one
   * was left on — and carrying the key makes that true on the render that
   * changes files, where the effect it replaces left the history tab showing
   * against the new file for one paint. */
  const [tabFor, setTabFor] = useState<{ key: string; tab: Tab }>({ key: '', tab: 'content' })
  const tabKey = path?.value ?? ''
  const tab = tabFor.key === tabKey ? tabFor.tab : 'content'
  const setTab = useCallback((next: Tab) => setTabFor({ key: tabKey, tab: next }), [tabKey])
  const [mode, setMode] = useState<RenderMode>('rendered')
  // Defaults to author because this console's reader is the person building the
  // course — the learner view is a preview of somebody else's screen.
  const [audience, setAudience] = useState<ComponentAudience>('author')

  const showRendered = (path?.isMarkdown ?? false) && tab === 'content' && mode === 'rendered'
  const lesson = useLesson(sessionId, path, audience, scrub, showRendered)

  if (!path) {
    return (
      <EmptyState
        heading="No file selected."
        detail="Pick a file above to read it as of the selected event, or open its full revision history."
      />
    )
  }

  return (
    <>
      <div className="file-view-head">
        <span className="fv-path">{path.value}</span>

        {path.isMarkdown && tab === 'content' ? (
          <TabGroup
            options={[
              { id: 'rendered', label: 'rendered' },
              { id: 'source', label: 'source' },
            ]}
            active={mode}
            onChange={setMode}
          />
        ) : null}

        {/* Only for a document that actually has components. A view switch on a
            file with nothing to withhold is a control that does nothing, and
            the header is already crowded. */}
        {showRendered && lesson.interactive ? (
          <TabGroup
            options={[
              {
                id: 'author',
                label: 'author',
                explanation:
                  'Everything the file contains, including answers and authoring warnings.',
              },
              {
                id: 'learner',
                label: 'learner',
                explanation:
                  'Preview what a learner is sent: answers and rationales withheld, and graded on the server.',
              },
            ]}
            active={audience}
            // Switching refetches rather than filters, because which fields
            // exist is the server's decision — that is the whole point of doing
            // the projection there — and the client has no key to hide anyway.
            onChange={setAudience}
          />
        ) : null}

        <TabGroup
          options={[
            { id: 'content', label: 'contents' },
            { id: 'history', label: 'history' },
          ]}
          active={tab}
          onChange={setTab}
        />
      </div>

      {tab === 'content' ? (
        <Contents
          sessionId={sessionId}
          path={path}
          scrub={scrub}
          rendered={showRendered}
          lesson={lesson}
        />
      ) : (
        <FileHistory sessionId={sessionId} path={path} />
      )}
    </>
  )
}

const Contents = ({
  sessionId,
  path,
  scrub,
  rendered,
  lesson,
}: {
  sessionId: SessionId
  path: FilePath
  scrub: ScrubPoint
  rendered: boolean
  lesson: Lesson
}) => {
  const { workspace } = useContainer()
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

  if (contents.isError) {
    const error = contents.error
    if (error instanceof ApiError && error.isNotFound) {
      return (
        <EmptyState
          heading={ScrubPoint.isHistorical(scrub) ? 'Not in the workspace here.' : 'No such file.'}
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
        heading="Could not read this file"
        message={errorMessage(error)}
        onRetry={() => void contents.refetch()}
      />
    )
  }

  if (contents.data === undefined) return <Loading what="file" />

  const stale = clsx(contents.isPlaceholderData && 'stale')

  // The parsed document wins when it has components to show; a markdown file
  // without any renders through the path it always did, which keeps the common
  // case free of a second render tree.
  if (rendered && lesson.interactive && lesson.doc) {
    return (
      <div className={stale}>
        <LessonDocument doc={lesson.doc} attempts={attempts} />
      </div>
    )
  }

  return rendered ? (
    <Markdown source={contents.data} className={stale} />
  ) : (
    <CodeBlock text={contents.data} className={stale} />
  )
}

/** A row of mutually exclusive tabs.
 *
 * The header holds three of these and they behaved identically; three separate
 * button components was three places for the active-state rule to drift. */
const TabGroup = <T extends string>({
  options,
  active,
  onChange,
}: {
  options: readonly { id: T; label: string; explanation?: string }[]
  active: T
  onChange: (id: T) => void
}) => (
  <div className="tabs">
    {options.map((option) => (
      <TabButton key={option.id} option={option} active={active} onChange={onChange} />
    ))}
  </div>
)

/** One tab, wrapped in its explanation only when it has one.
 *
 * Two of the eight tabs in this header carry a sentence — author and learner,
 * where the difference between the two views is the whole reason the switch
 * exists and is not deducible from the two words on the buttons. The other six
 * are self-describing, and wrapping them anyway would put a `Tooltip` around
 * "contents" for the sake of uniformity. */
const TabButton = <T extends string>({
  option,
  active,
  onChange,
}: {
  option: { id: T; label: string; explanation?: string }
  active: T
  onChange: (id: T) => void
}) => {
  const button = (
    <button
      type="button"
      className={clsx('tab', option.id === active && 'active')}
      onClick={() => {
        if (option.id !== active) onChange(option.id)
      }}
    >
      {option.label}
    </button>
  )
  if (!option.explanation) return button
  return (
    <Tooltip asChild explanation={option.explanation}>
      {button}
    </Tooltip>
  )
}
