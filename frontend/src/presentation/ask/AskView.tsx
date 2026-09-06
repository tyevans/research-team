import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { useContainer } from '@app/container-context.tsx'
import { useInteractionLog } from '@app/interaction-log-provider.tsx'
import { createAskStore } from '@application/ask/ask-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { storedTranscript } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'
import { newId } from '@infrastructure/identity/new-id.ts'
import { projectHref } from '@presentation/routing/routes.ts'
import { navigate } from '@presentation/routing/use-route.ts'

import { AskPage } from './AskPage.tsx'

/** Ask the project: a read-only conversation over everything it has gathered.
 *
 * A third facet beside Course and Research rather than a page of its own, so
 * the three are reached by the same nav and the URL keeps saying which project
 * you are in.
 *
 * This file is the store and nothing else. Everything it draws lives in
 * `AskPage`, which takes props -- see there for what that buys.
 *
 * **Two modes over one page, chosen by the URL.** `#/p/<id>/ask` is the live
 * conversation; `#/p/<id>/ask/<conversationId>` is a stored one, read. They
 * share `AskPage` rather than forking into a second view because a stored turn
 * and a live one are the same thing once it has settled -- `storedTranscript`
 * is the whole of the difference, and it is a pure function in the domain.
 */
export const AskView = ({
  projectId,
  /** The stored conversation named by the URL, or `null` for a live chat.
   *
   * A prop rather than part of the `key`, which is `DialogueView`'s correction
   * and applies here for the same reason: keyed on it, the view would remount
   * the instant the reader opened one, and the live store's chat id would be
   * re-minted behind them. */
  conversationId: storedId = null,
}: {
  projectId: ProjectId
  conversationId?: string | null
}) => {
  const { ask } = useContainer()
  const log = useInteractionLog()

  /** One store per project, as `GraphPane` builds one per project: the chat id
   *  identifies a server-side conversation scoped to this project, and a store
   *  shared across projects would carry one project's questions to another. */
  const store = useMemo(
    () => createAskStore({ ask, projectId, newChatId: newId, emitter: log }),
    [ask, projectId, log],
  )

  /** The history list, fetched once per project rather than per mount of the
   *  empty state.
   *
   * `enabled` on the live page only: a reader looking at a stored conversation
   * is not shown the list (the thread is not empty), so fetching it there
   * would be a request whose result nothing draws. */
  const history = useQuery({
    queryKey: ['asks', projectId],
    queryFn: () => ask.conversations(projectId),
    enabled: storedId === null,
  })

  const stored = useQuery({
    queryKey: ['ask', projectId, storedId],
    // Guarded by `enabled`, so the non-null assertion is the one this codebase
    // already accepts at a react-query boundary -- the query does not run with
    // a null id.
    queryFn: () => ask.conversation(projectId, storedId!),
    enabled: storedId !== null,
  })

  // Read through the hook during render; reach actions through `getState()` in
  // handlers, so a handler never closes over a stale slice.
  const liveTranscript = store((state) => state.transcript)
  const asking = store((state) => state.asking)
  const error = store((state) => state.error)
  // The server's id for this conversation, not `chatId`: that one is minted
  // in the browser and never reaches storage, so an attempt POST built from
  // it would name a conversation the server has never heard of. Null until
  // the stream's first frame arrives -- see `AskPage` for how a turn
  // rendered before then is kept from posting under a guess.
  const liveConversationId = store((state) => state.conversationId)

  const reading = storedId !== null
  const transcript = reading ? storedTranscript(stored.data) : liveTranscript

  return (
    <AskPage
      projectId={projectId}
      transcript={transcript}
      conversationId={reading ? storedId : liveConversationId}
      asking={asking}
      // A stored conversation that will not load is the same kind of thing to
      // a reader as a question that would not go through: the page has nothing
      // to show and has to say why. Rendered through the banner the live path
      // already has rather than a second empty state.
      error={reading ? (stored.error ? errorMessage(stored.error) : null) : error}
      onAsk={(question) => void store.getState().send(question)}
      // On a stored conversation "New chat" leaves it rather than clearing it:
      // there is nothing here to clear, and the reader's way back to a page
      // they can type on is the live URL.
      onReset={
        reading
          ? () => navigate(projectHref(projectId, { facet: 'ask', id: null }))
          : () => void store.getState().reset()
      }
      history={history.data ?? []}
      historyError={history.error ? errorMessage(history.error) : null}
      reading={reading}
    />
  )
}
