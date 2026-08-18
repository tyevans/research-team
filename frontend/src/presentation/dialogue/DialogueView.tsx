import { useEffect, useState } from 'react'

import { useContainer } from '@app/container-context.tsx'
import { createDialogueStore } from '@application/dialogue/dialogue-store.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'
import { projectHref } from '@presentation/routing/routes.ts'
import { navigate } from '@presentation/routing/use-route.ts'

import { DialoguePage } from './DialoguePage.tsx'

/** A socratic dialogue on this project: the console asks, the reader answers.
 *
 * A facet beside `ask` and intercepted the same way -- see `App.tsx` -- because
 * a dialogue is one conversation with no parts worth a URL segment beyond its
 * own id.
 *
 * This file is the store and nothing else, which is `AskView`'s split: the page
 * takes props, so nothing between a reader and the first pixel is a container
 * and a fake repository.
 */
export const DialogueView = ({
  projectId,
  /** The dialogue named by the URL, or `null` for `#/p/<id>/dialogue` with
   *  nothing after it.
   *
   * Read at all, which it was not: this view took `projectId` alone, nothing
   * wrote the minted id into the hash, and the store therefore began every
   * mount at `dialogueId: null`. `refreshProgress` short-circuited on its
   * guard, the only reachable dialogue was one just minted with zero attempts,
   * and `progress` could only ever be `{}` in a real browser -- so a refresh
   * did not lose the grades, it lost the dialogue. */
  dialogueId: routeDialogueId,
}: {
  projectId: ProjectId
  dialogueId: string | null
}) => {
  const { dialogues } = useContainer()

  /** One store per dialogue, seeded from the URL.
   *
   * State rather than a memo on `routeDialogueId`, and the difference is the
   * whole reason this reads awkwardly. This view NAVIGATES when a dialogue is
   * minted, so `routeDialogueId` changes from null to the store's own id one
   * render after `start` resolves. A memo keyed on it would rebuild the store
   * at exactly that moment and throw away the transcript that just streamed --
   * an opening question the reader paid a model call for, replaced by an empty
   * thread. So the store is rebuilt only when the URL names a dialogue this
   * store is NOT already on, which is a reader following a link to a different
   * one. */
  const [store, setStore] = useState(() =>
    createDialogueStore({ dialogues, projectId, dialogueId: routeDialogueId }),
  )
  /** The route the store was last reconciled against.
   *
   * A latch, not a convenience, and plain inequality against
   * `store.getState().dialogueId` will not do: between `start` resolving and
   * the navigation below landing, the store holds the minted id and the route
   * still holds null. That is a mismatch that must NOT rebuild anything -- it
   * is this view's own navigation, one render out of step. What must rebuild
   * is the route *changing* to name a dialogue this store is not on, which is
   * a reader following a link to a different one.
   *
   * Adjusted during render rather than in an effect: React re-runs this render
   * before committing, so the new store is the one that draws, and the lint
   * rule against `setState` in an effect is pointing at the real cost -- the
   * effect version drew the old dialogue for one frame first. */
  const [reconciledTo, setReconciledTo] = useState(routeDialogueId)
  if (reconciledTo !== routeDialogueId) {
    setReconciledTo(routeDialogueId)
    if (store.getState().dialogueId !== routeDialogueId) {
      setStore(createDialogueStore({ dialogues, projectId, dialogueId: routeDialogueId }))
    }
  }

  // Read through the hook during render; reach actions through `getState()` in
  // handlers, so a handler never closes over a stale slice.
  const transcript = store((state) => state.transcript)
  const goal = store((state) => state.goal)
  const stoppingCondition = store((state) => state.stoppingCondition)
  // The opening question, off the dialogue row. Not `pendingBlocks` -- the
  // store no longer has one, and `DialogueThread` says why a later frame's
  // blocks are a question already drawn.
  const openingBlocks = store((state) => state.openingBlocks)
  // The server's id, null until `start` returns it. `DialoguePage` chooses
  // which of the two things its one composer is asking for from this.
  const dialogueId = store((state) => state.dialogueId)
  /** What the server remembers of this reader's answers. Empty until the load
   *  below resolves, which is honest: an unanswered widget and an unloaded one
   *  are the same thing to a reader looking at them. */
  const progress = store((state) => state.progress)
  const replying = store((state) => state.replying)
  const starting = store((state) => state.starting)
  const error = store((state) => state.error)
  const progressUnavailable = store((state) => state.progressUnavailable)
  // Read here rather than left on the store: a field nothing renders is a
  // silo, and this one is the whole of what tells a returning reader their
  // dialogue finished instead of showing them a failure.
  const concluded = store((state) => state.concluded)

  /** Put the minted id in the hash, which is what makes a dialogue a place
   *  rather than a session.
   *
   * `replace`, not a push: `#/p/<id>/dialogue` with nothing after it is the
   * blank composer the reader just left, and a Back that returned them to it
   * would look like the dialogue had been discarded.
   *
   * An effect on the id rather than a `.then` on `start`: the id arrives on
   * the stream's first frame, so `reply` can set it too, and one rule here
   * covers both without either action knowing about the router. */
  useEffect(() => {
    if (dialogueId === null || dialogueId === routeDialogueId) return
    navigate(projectHref(projectId, { facet: 'dialogue', id: dialogueId }), { replace: true })
  }, [dialogueId, routeDialogueId, projectId])

  /** Load the marked answers once this dialogue has an id.
   *
   * Keyed on `dialogueId` rather than run once on mount: the id is null until
   * `start` returns, so a bare `[]` effect would fire against nothing and
   * never fire again -- and the case this whole route exists for, a reader
   * returning to a dialogue that already has answers in it, arrives with an
   * id already set. The store's action is a no-op on a null id, so the first
   * run costs nothing.
   *
   * `void`: the action never rejects (it swallows its own failure and says
   * why), so there is nothing here to handle. */
  useEffect(() => {
    void store.getState().refreshProgress()
  }, [store, dialogueId])

  return (
    <DialoguePage
      projectId={projectId}
      transcript={transcript}
      goal={goal}
      stoppingCondition={stoppingCondition}
      openingBlocks={openingBlocks}
      dialogueId={dialogueId}
      progress={progress}
      replying={replying}
      starting={starting}
      error={error}
      progressUnavailable={progressUnavailable}
      concluded={concluded}
      onStart={(topic) => void store.getState().start(topic)}
      onReply={(reply) => void store.getState().send(reply)}
    />
  )
}
