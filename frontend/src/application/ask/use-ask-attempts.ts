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
 * discovering it on refresh.
 *
 * `conversationId` is nullable because the server names the conversation in
 * the stream's *first* frame, and a component can render before that frame
 * lands -- an early `delta` carries no id, but a widget only ever appears
 * inside `blocks`, which travel on the `answer` frame that settles the turn.
 * In practice the id is already known by the time a widget exists to submit
 * against. This still guards the gap rather than assume it away: posting an
 * attempt under a guessed id -- `chatId`, say -- would silently grade against
 * a conversation the server never opened, which is exactly the bug this hook
 * replaced. Null keeps the widget interactive but makes `submit` a no-op
 * instead, the same shape `useAttempts` uses for "no file open". */
export const useAskAttempts = (
  projectId: ProjectId,
  conversationId: string | null,
  position: number,
): AttemptsApi => {
  const { ask } = useContainer()
  const api = useAttemptMachine(`${conversationId ?? 'pending'}:${String(position)}`, {
    stored: null,
    submit: (block, response) =>
      ask.submitAskAttempt(projectId, conversationId!, {
        position,
        componentId: block.id,
        response,
      }),
  })
  return {
    ...api,
    submit: (block, response) => (conversationId ? api.submit(block, response) : Promise.resolve()),
  }
}
