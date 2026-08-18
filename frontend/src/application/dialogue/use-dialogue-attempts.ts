import { useContainer } from '@app/container-context.tsx'
import { useAttemptMachine, type AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

/** Every widget's state for one exchange, and the one call that changes it on
 *  the server.
 *
 * A sibling of `use-ask-attempts.ts`, and the difference is what the surfaces
 * do with an answer rather than how they collect one: an ask discards the
 * attempt, and a dialogue RECORDS it against the dialogue id. That is the
 * whole argument for this surface being its own principal, so it would be odd
 * to reach it through the ask's hook.
 *
 * `stored` is null all the same, and for a different reason than the ask's:
 * the attempts are written and no read route serves them back yet (B114, Task
 * 6's progress route). So a refresh still shows empty widgets today, and this
 * hook will gain the loader rather than change shape when it does not.
 *
 * `dialogueId` is nullable because the page renders before `start` returns the
 * server-minted id. Posting under a guessed id would grade against a dialogue
 * the server never opened -- the same bug `useAskAttempts` guards, and worse
 * here, because this one persists what it grades. Null keeps the widget
 * interactive and makes `submit` a no-op.
 *
 * `position` is the TURN's position, carried straight off the `prompt` frame.
 * It is the only place it survives to, and it is what the attempts route
 * matches against a `SocraticTurnRow` -- see `DialogueThread` for the one
 * question that has no such row and therefore cannot use this hook.
 */
export const useDialogueAttempts = (
  projectId: ProjectId,
  dialogueId: string | null,
  position: number,
): AttemptsApi => {
  // Plural, as every key in this container is.
  const { dialogues } = useContainer()
  const api = useAttemptMachine(`${dialogueId ?? 'pending'}:${String(position)}`, {
    stored: null,
    // The null check is inside the port rather than only on the returned
    // `submit` below, and both are kept. A non-null assertion here -- which is
    // what this was, and what `useAskAttempts` still is -- is safe only because
    // the wrapper short-circuits, which puts the assertion and its guard in two
    // separate places: a future caller reaching this port directly would render
    // `null` into the URL path and grade against a dialogue that does not
    // exist.
    //
    // Rejecting rather than resolving, because the port owes a `Verdict` and
    // there is no honest one to invent: a resolved no-op would leave the widget
    // looking marked. `useAttemptMachine`'s own `.catch` writes the message
    // into the widget's error, so the failure is visible instead of silent.
    // No reader reaches it today -- the wrapper below still returns first.
    submit: (block, response) =>
      dialogueId === null
        ? Promise.reject(new Error('This dialogue has not been started yet.'))
        : dialogues.submitDialogueAttempt(projectId, dialogueId, {
            position,
            componentId: block.id,
            response,
          }),
  })
  // Kept as well as the guard above, and not redundant with it: this one stops
  // the attempt machine transitioning to a submitted state at all, so a widget
  // rendered before `start` returns does not show a graded-looking result it
  // never got.
  return {
    ...api,
    submit: (block, response) => (dialogueId ? api.submit(block, response) : Promise.resolve()),
  }
}
