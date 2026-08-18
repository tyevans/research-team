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
    submit: (block, response) =>
      dialogues.submitDialogueAttempt(projectId, dialogueId!, {
        position,
        componentId: block.id,
        response,
      }),
  })
  return {
    ...api,
    submit: (block, response) => (dialogueId ? api.submit(block, response) : Promise.resolve()),
  }
}
