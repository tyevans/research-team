/** The ask page's store: wires the streaming repository to the transcript
 *  fold and adds the guarantees neither of those provides on its own --
 *  refusing to double-send while a turn is running, settling a turn that
 *  fails before its first frame, and keeping one chat id per conversation
 *  so every question in it lands on the same server-side session.
 */
import { create } from 'zustand'

import type { Emitter } from '@application/interaction-log/emitter.ts'
import { errorMessage } from '@application/ports/errors.ts'
import type { AskRepository } from '@application/ports/repositories.ts'
import { applyEvent, asked, type AskTranscript } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

export interface AskState {
  readonly transcript: AskTranscript
  readonly asking: boolean
  readonly error: string | null
  readonly chatId: string
  /** The server's id for the open conversation -- distinct from `chatId` on
   *  purpose. `chatId` is minted here and only ever used to ask the server to
   *  open a conversation; the server's own id is what an attempt POST and a
   *  history route have to name, and the two are never the same string. Null
   *  until the stream's first frame arrives, which is why an attempt cannot
   *  be submitted before then -- see `AskPage`'s widgets. */
  readonly conversationId: string | null
  send(question: string): Promise<void>
  reset(): Promise<void>
}

export type AskStore = ReturnType<typeof createAskStore>

export const createAskStore = ({
  ask,
  projectId,
  newChatId,
  emitter,
}: {
  ask: AskRepository
  projectId: ProjectId
  newChatId: () => string
  /** Optional so the many tests that build this store need no change. A
   *  store that records nothing is correct in a test. */
  emitter?: Pick<Emitter, 'record'>
}) => {
  // The last question asked on the current `chatId`, and how many times in a
  // row it has been asked. Reset by `reset()`, which mints a new chat -- the
  // same question asked in a fresh conversation is a new start, not a second
  // attempt at the old one.
  //
  // This counts *repeats*, not turns, and the difference is the whole point.
  // An earlier draft advanced on every question in the conversation, which
  // made a productive five-turn chat indistinguishable from someone asking
  // the same thing five ways because the answer was wrong -- and worse, made
  // the feature people used best read as the one with the most friction.
  // `direction.md` §3 reads this kind as repair; measuring conversation
  // length under that name is a confident wrong number.
  //
  // Identical trimmed text is a narrow definition and deliberately so: it is
  // the same one the search side uses, it is the only judgement a store can
  // make without reading English, and it under-counts (a rephrased retry is
  // missed) rather than over-counting. An absent signal is recoverable; a
  // polluted one is not.
  let lastQuestion: string | null = null
  let repeats = 0

  return create<AskState>((set, get) => ({
    transcript: [],
    asking: false,
    error: null,
    chatId: newChatId(),
    conversationId: null,

    async send(question) {
      const trimmed = question.trim()
      // The server refuses a second question on a busy chat with a 409; not
      // sending it in the first place is the same answer without the round
      // trip.
      if (!trimmed || get().asking) return

      // Emitted before the `await` below, per the brief: the act is the
      // submission, not the eventual answer, and a turn that fails partway
      // through streaming should still show up as something that was asked.
      emitter?.record('AskSubmitted', { query_text: trimmed })
      if (lastQuestion === trimmed) {
        repeats += 1
      } else {
        lastQuestion = trimmed
        repeats = 1
      }
      if (repeats > 1) {
        emitter?.record('ActionRetried', { action_kind: 'ask', attempt_number: repeats })
      }

      set((state) => ({ transcript: asked(state.transcript, trimmed), asking: true, error: null }))
      try {
        await ask.ask(projectId, get().chatId, trimmed, (event) => {
          // Intercepted rather than folded into the transcript: this is the
          // one event with nothing to do with a turn, and the store -- not
          // the pure fold -- is what other code reads a conversation id from.
          if (event.type === 'conversation') {
            set({ conversationId: event.conversationId })
            return
          }
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
      lastQuestion = null
      repeats = 0
      set({ transcript: [], error: null, chatId: newChatId(), conversationId: null })
      try {
        await ask.forget(projectId, previous)
      } catch {
        // The server's copy expires on its own, and refusing to clear the
        // page would strand the reader in a conversation they asked to leave.
      }
    },
  }))
}
