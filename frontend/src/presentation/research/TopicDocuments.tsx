import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import clsx from 'clsx'

import { useAttempts } from '@application/lesson/use-attempts.ts'
import { useLesson } from '@application/lesson/use-lesson.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { TopicDocuments as Documents } from '@domain/research/topic-document.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { FilePath } from '@domain/shared/file-path.ts'
import type { ProjectId, SessionId, TopicId } from '@domain/shared/identifier.ts'

import { Markdown } from '../common/content.tsx'
import { EmptyState, ErrorBox, Loading } from '../common/primitives.tsx'
import { LessonDocument } from '../lesson/LessonDocument.tsx'
import { useFrameRefresh } from '../shell/use-frame-refresh.ts'

/** One document's tab, without the border and text colour that say whether it
 *  is the open one.
 *
 * `aria-pressed` carries that fact for a screen reader and the two colours draw
 * it; both are set from the same condition, which is what `.is-on` did before
 * the class names went. */
const DOCUMENT_TAB =
  'cursor-pointer rounded-md border border-solid bg-transparent px-[8px] py-[2px] font-mono text-xs'

/** What a dispatch wrote about this topic, readable from the research view.
 *
 * **Without this, actions 2 and 3 write files nobody can find.** A dispatch
 * writes on a session it creates and releases; the file is on the live feed,
 * is scrubbable and is diffable, and is reachable only by someone who already
 * knows which session id to look under. The research view never did.
 *
 * **It reuses the session-keyed readers rather than replacing them.** The
 * listing route hands back the `(sessionId, at)` pair that the project's files
 * currently fold out of, and everything below that point is `FileView`'s own
 * machinery unchanged — `useLesson` for the parse, `useAttempts` for the
 * grading, `readFile` for the bytes. The alternative was a project-scoped copy
 * of all three, which would have had to agree with the originals about
 * scrubbing, component withholding and attempt keying, and would not have.
 *
 * The reader is always the *author* audience here. This pane is the person who
 * asked for the document looking at what they got; withholding answers from
 * them would be withholding them from the author, which is the one case
 * `ComponentAudience` exists to keep apart. A learner reads a lesson through
 * the session route, which has the toggle.
 */
export const TopicDocuments = ({
  projectId,
  topicId,
}: {
  projectId: ProjectId
  topicId: TopicId
}) => {
  const { topics } = useContainer()
  const [open, setOpen] = useState<string | null>(null)

  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: queryKeys.topicDocuments(projectId, topicId),
    queryFn: () => topics.documents(projectId, topicId),
  })

  // Scoped to *this* topic's own dispatches rather than the project's, because
  // a listing is one directory and a dispatch on another topic cannot change
  // it. `useDispatchBoard` cannot do this on the pane's behalf: its callback is
  // handed no frame, and a project-wide invalidation would re-read forty
  // listings for one file.
  useFrameRefresh(
    true,
    (frame) =>
      frame.kind === 'dispatch' &&
      frame.projectId === projectId &&
      frame.dispatch.topicId === topicId,
    () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.topicDocuments(projectId, topicId),
      })
    },
  )

  if (query.isPending) return <Loading what="documents" />

  if (query.isError) {
    return (
      <ErrorBox
        heading="Could not list this topic's documents"
        message={errorMessage(query.error)}
        onRetry={() => void query.refetch()}
      />
    )
  }

  const board: Documents = query.data
  if (board.documents.length === 0 || board.sessionId === null) {
    return (
      <EmptyState
        heading="Nothing written yet"
        // Names the directory rather than saying "no documents": a reader who
        // dispatched a moment ago wants to know *where* it will appear, and a
        // reader whose topic moved in the list needs the path to notice that
        // the directory it was written to is not this one.
        detail={`A dispatch writes to ${board.directory}. Nothing is there yet.`}
      />
    )
  }

  const selected = board.documents.find((document) => document.path.value === open)

  return (
    // `.topic-documents` was the outer name here and declared nothing — a fifth
    // undressed class beyond the four the slice plan enumerated. It is dropped
    // rather than dressed: the list below carries its own bottom margin, the
    // pane around it supplies the padding, and a wrapper with no declarations
    // was doing nothing but occupying a name.
    <div>
      <ul className="m-0 mb-[10px] flex list-none flex-wrap gap-[6px] p-0">
        {board.documents.map((document) => (
          <li key={document.path.value}>
            <button
              type="button"
              aria-pressed={document.path.value === open}
              // The tone is per branch rather than a base colour plus an
              // override: two `text-*` (or two `border-*`) utilities on one
              // element resolve in Tailwind's emission order, not the
              // attribute's.
              className={clsx(
                DOCUMENT_TAB,
                document.path.value === open
                  ? 'border-accent text-accent'
                  : 'border-line text-fg-dim',
              )}
              onClick={() => setOpen(document.path.value === open ? null : document.path.value)}
            >
              {document.name}
            </button>
          </li>
        ))}
      </ul>
      {selected ? (
        <DocumentBody
          projectId={projectId}
          sessionId={board.sessionId}
          path={selected.path}
          // HEAD, written here rather than read off the response. The server
          // sent an `at` beside `sessionId` until 2026-08-27, when it was
          // measured to name a scrub point at which a document in the same
          // response did not exist; the files a project has are folded to
          // HEAD, so this is the point they were folded at.
          scrub={ScrubPoint.head()}
        />
      ) : null}
    </div>
  )
}

/** One document, rendered the way the session viewer renders it.
 *
 * A separate component because `useLesson`, `useAttempts` and the contents
 * query are all keyed by the path, and hooks cannot be called conditionally —
 * so "no document selected" has to be the absence of this component rather
 * than a branch inside it.
 */
const DocumentBody = ({
  projectId,
  sessionId,
  path,
  scrub,
}: {
  projectId: ProjectId
  sessionId: SessionId
  path: FilePath
  scrub: ScrubPoint
}) => {
  const { workspace } = useContainer()
  const lesson = useLesson(sessionId, path, 'author', scrub, true)
  const attempts = useAttempts(sessionId, path, scrub)

  const contents = useQuery({
    queryKey: queryKeys.file(sessionId, path, scrub),
    queryFn: () => workspace.readFile(sessionId, path, scrub),
  })

  if (contents.isPending) return <Loading what="document" />

  if (contents.isError) {
    return (
      <ErrorBox
        heading="Could not read this document"
        message={errorMessage(contents.error)}
        onRetry={() => void contents.refetch()}
      />
    )
  }

  // The parsed document wins when it has components to show; one without any
  // renders through the plain markdown path, which keeps the common case --
  // and `understanding.md` is deliberately the common case, since a synthesis
  // is explanation and gets no widget guidance -- free of a second render tree.
  if (lesson.interactive && lesson.doc) {
    return <LessonDocument doc={lesson.doc} attempts={attempts} />
  }

  return <Markdown source={contents.data} projectId={projectId} />
}
