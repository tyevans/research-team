import { useAttemptMachine, type AttemptsApi } from '@application/lesson/use-attempts.ts'
import { useContainer } from '@app/container-context.tsx'
import type { ProjectId } from '@domain/shared/identifier.ts'

/** Every widget's state for one ask turn, and the one call that changes it on
 *  the server.
 *
 * Scoped to a turn for the reason the lesson hook is scoped to a file: an
 * answer typed against one question is not an answer to the next, and a stale
 * verdict shown against a different widget would be worse than losing it.
 *
 * `stored` is null and `saveChecklist` is absent, and both are the same fact
 * from two directions: an ask records nothing, so there is no history to
 * restore and no tick to keep. The reader is told this in the page rather than
 * discovering it on refresh. */
export const useAskAttempts = (
  projectId: ProjectId,
  conversationId: string,
  position: number,
): AttemptsApi => {
  const { ask } = useContainer()
  return useAttemptMachine(`${conversationId}:${String(position)}`, {
    stored: null,
    submit: (block, response) =>
      ask.submitAskAttempt(projectId, conversationId, {
        position,
        componentId: block.id,
        response,
      }),
  })
}
