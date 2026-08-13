import { useMemo } from 'react'

import { useContainer } from '@app/container-context.tsx'
import { createAskStore } from '@application/ask/ask-store.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'
import { projectHref } from '../routing/routes.ts'
import { AskComposer } from './AskComposer.tsx'
import { AskThread } from './AskThread.tsx'

/** Ask the project: a read-only conversation over everything it has gathered.
 *
 * A third facet beside Course and Research rather than a page of its own, so
 * the three are reached by the same `.view-head-actions` links and the URL
 * keeps saying which project you are in.
 *
 * Ephemeral, and said so in three places -- the subtitle, the empty thread and
 * the composer's hint. That is repetition on purpose: the cost of a reader
 * missing it is coming back tomorrow for an answer that is gone.
 */
export const AskView = ({ projectId }: { projectId: ProjectId }) => {
  const { ask } = useContainer()

  /** One store per project, as `GraphPane` builds one per project: the chat id
   *  identifies a server-side conversation scoped to this project, and a store
   *  shared across projects would carry one project's questions to another. */
  const store = useMemo(
    () => createAskStore({ ask, projectId, newChatId: () => crypto.randomUUID() }),
    [ask, projectId],
  )

  // Read through the hook during render; reach actions through `getState()` in
  // handlers, so a handler never closes over a stale slice.
  const transcript = store((state) => state.transcript)
  const asking = store((state) => state.asking)
  const error = store((state) => state.error)

  return (
    <section className="view view-ask">
      <div className="view-head">
        <div>
          <h1>Ask</h1>
          <p className="sub">
            Answers come from this project’s sources and findings. Not saved — the conversation goes
            when you leave.
          </p>
        </div>
        <div className="view-head-actions">
          <Button tone="quiet" onClick={() => void store.getState().reset()}>
            New chat
          </Button>
          {/* The project page with no selection, which is the course today. */}
          <a className="btn btn-quiet" href={projectHref(projectId)}>
            Course
          </a>
          <a className="btn btn-quiet" href={projectHref(projectId, { facet: 'entity', id: null })}>
            Research
          </a>
        </div>
      </div>

      {/* A refusal made before the stream started -- a busy chat, a dead
          network -- never becomes an answer, so it has nowhere to live in the
          transcript's own error and needs saying here. An unknown project is
          *not* one of these: those routes never check, so it arrives as an
          in-band error frame on a 200 and lands in the failed turn. */}
      {error ? (
        <div className="error-box ask-banner" role="alert">
          <strong>That question did not go through.</strong>
          {error}
        </div>
      ) : null}

      <AskThread projectId={projectId} transcript={transcript} />

      <AskComposer asking={asking} onAsk={(question) => void store.getState().send(question)} />
    </section>
  )
}
