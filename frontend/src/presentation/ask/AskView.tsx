import { useMemo } from 'react'

import { useContainer } from '@app/container-context.tsx'
import { createAskStore } from '@application/ask/ask-store.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'
import { newId } from '@infrastructure/identity/new-id.ts'

import { AskPage } from './AskPage.tsx'

/** Ask the project: a read-only conversation over everything it has gathered.
 *
 * A third facet beside Course and Research rather than a page of its own, so
 * the three are reached by the same nav and the URL keeps saying which project
 * you are in.
 *
 * This file is the store and nothing else. Everything it draws lives in
 * `AskPage`, which takes props -- see there for what that buys.
 */
export const AskView = ({ projectId }: { projectId: ProjectId }) => {
  const { ask } = useContainer()

  /** One store per project, as `GraphPane` builds one per project: the chat id
   *  identifies a server-side conversation scoped to this project, and a store
   *  shared across projects would carry one project's questions to another. */
  const store = useMemo(
    () => createAskStore({ ask, projectId, newChatId: newId }),
    [ask, projectId],
  )

  // Read through the hook during render; reach actions through `getState()` in
  // handlers, so a handler never closes over a stale slice.
  const transcript = store((state) => state.transcript)
  const asking = store((state) => state.asking)
  const error = store((state) => state.error)
  // The server's id for this conversation, not `chatId`: that one is minted
  // in the browser and never reaches storage, so an attempt POST built from
  // it would name a conversation the server has never heard of. Null until
  // the stream's first frame arrives -- see `AskPage` for how a turn
  // rendered before then is kept from posting under a guess.
  const conversationId = store((state) => state.conversationId)

  return (
    <AskPage
      projectId={projectId}
      transcript={transcript}
      conversationId={conversationId}
      asking={asking}
      error={error}
      onAsk={(question) => void store.getState().send(question)}
      onReset={() => void store.getState().reset()}
    />
  )
}
