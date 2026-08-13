/** The ask page's store: wires the streaming repository to the transcript
 *  fold and adds the guarantees neither of those provides on its own --
 *  refusing to double-send while a turn is running, settling a turn that
 *  fails before its first frame, and keeping one chat id per conversation
 *  so every question in it lands on the same server-side session.
 */
import { create } from 'zustand'

import { errorMessage } from '@application/ports/errors.ts'
import type { AskRepository } from '@application/ports/repositories.ts'
import { applyEvent, asked, type AskTranscript } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

export interface AskState {
  readonly transcript: AskTranscript
  readonly asking: boolean
  readonly error: string | null
  readonly chatId: string
  send(question: string): Promise<void>
  reset(): Promise<void>
}

export type AskStore = ReturnType<typeof createAskStore>

export const createAskStore = ({
  ask,
  projectId,
  newChatId,
}: {
  ask: AskRepository
  projectId: ProjectId
  newChatId: () => string
}) =>
  create<AskState>((set, get) => ({
    transcript: [],
    asking: false,
    error: null,
    chatId: newChatId(),

    async send(question) {
      const trimmed = question.trim()
      // The server refuses a second question on a busy chat with a 409; not
      // sending it in the first place is the same answer without the round
      // trip.
      if (!trimmed || get().asking) return

      set((state) => ({ transcript: asked(state.transcript, trimmed), asking: true, error: null }))
      try {
        await ask.ask(projectId, get().chatId, trimmed, (event) => {
          set((state) => ({ transcript: applyEvent(state.transcript, event) }))
        })
      } catch (err) {
        const detail = errorMessage(err)
        // A failure before streaming starts (409, network) arrives as a
        // rejection rather than an in-band `error` event, so this is the only
        // place that path settles the open turn. Without it the turn spins
        // forever with no answer and no reason, which reads as a hung model
        // rather than a failed request.
        set((state) => ({
          transcript: applyEvent(state.transcript, { type: 'error', detail }),
          error: detail,
        }))
      } finally {
        set({ asking: false })
      }
    },

    async reset() {
      const previous = get().chatId
      set({ transcript: [], error: null, chatId: newChatId() })
      try {
        await ask.forget(projectId, previous)
      } catch {
        // The server's copy expires on its own, and refusing to clear the
        // page would strand the reader in a conversation they asked to leave.
      }
    },
  }))
