import { useEffect, useMemo } from 'react'

import { useContainer } from '@app/container-context.tsx'
import { createDialogueStore } from '@application/dialogue/dialogue-store.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

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
export const DialogueView = ({ projectId }: { projectId: ProjectId }) => {
  const { dialogues } = useContainer()

  /** One store per project, as `AskView` builds one per project -- and unlike
   *  the ask, there is no chat id to mint here: `start` returns the server's,
   *  because a dialogue id is a row key and a URL segment. Remounting between
   *  dialogues is `App.tsx`'s `key`, not this memo's business. */
  const store = useMemo(() => createDialogueStore({ dialogues, projectId }), [dialogues, projectId])

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
      onStart={(topic) => void store.getState().start(topic)}
      onReply={(reply) => void store.getState().send(reply)}
    />
  )
}
