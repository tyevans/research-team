/** The dialogue page's store: wires the streaming repository to the transcript
 *  fold and adds the three guarantees neither provides on its own.
 *
 * A sibling of `ask-store.ts`, and the differences are the point:
 *
 * 1. **There is no `newChatId`.** The ask mints a chat id in the browser and
 *    can therefore send immediately; a dialogue's id is an aggregate id, a row
 *    key and a URL segment, so the server mints it and it arrives from
 *    `start`. Every guard below follows from that.
 * 2. **The framing lives here, not in the transcript.** `goal`,
 *    `stoppingCondition` and `pendingBlocks` are the dialogue's framing, not
 *    turns in it; a transcript that held them would draw them as something the
 *    reader has to answer.
 * 3. **The store settles a stream that ended without settling itself.** The
 *    fold is pure and cannot see a body stop.
 */
import { create } from 'zustand'

import { errorMessage } from '@application/ports/errors.ts'
import type { DialogueRepository } from '@application/ports/repositories.ts'
import { answered, applyEvent, type DialogueTranscript } from '@domain/dialogue/conversation.ts'
import type { DocumentBlock } from '@domain/lesson/document.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

export interface DialogueState {
  readonly transcript: DialogueTranscript
  readonly dialogueId: string | null
  readonly goal: string
  readonly stoppingCondition: string
  /** The question the reader is answering right now: the opening one on a
   *  fresh dialogue, the outstanding one on a resumed one. Blocks, never a
   *  string. */
  readonly pendingBlocks: readonly DocumentBlock[]
  readonly replying: boolean
  readonly starting: boolean
  readonly error: string | null
  start(topic: string): Promise<void>
  send(reply: string): Promise<void>
}

export type DialogueStore = ReturnType<typeof createDialogueStore>

export const createDialogueStore = ({
  dialogues,
  projectId,
}: {
  dialogues: DialogueRepository
  projectId: ProjectId
}) =>
  create<DialogueState>((set, get) => ({
    transcript: [],
    dialogueId: null,
    goal: '',
    stoppingCondition: '',
    pendingBlocks: [],
    replying: false,
    starting: false,
    error: null,

    async start(topic) {
      const trimmed = topic.trim()
      // Guarded as well as `send`, and for a worse failure -- this is the
      // guard that looks redundant and is not. Framing calls a model and takes
      // seconds, so a double-click on a slow connection posts twice: two
      // dialogues are minted, the page keeps the second, and the first is a
      // stream with a goal and an opening question that no client will ever
      // name again -- an orphan the reader paid a model call for and cannot
      // reach. `send`'s guard only saves a round trip the server would have
      // refused with a 409 anyway; this one prevents state nothing can clean
      // up. The test that fails without it is `does not start a second
      // dialogue while one is being framed`.
      if (!trimmed || get().starting || get().dialogueId !== null) return

      set({ starting: true, error: null })
      try {
        set({ dialogueId: await dialogues.start(projectId, trimmed) })
      } catch (err) {
        // Surfaced rather than swallowed: the route answers 502 when the model
        // botched the framing, and a store that kept quiet would leave the page
        // on an empty dialogue whose composer 404s on every send.
        set({ error: errorMessage(err) })
      } finally {
        set({ starting: false })
      }
    },

    async send(reply) {
      const trimmed = reply.trim()
      // No dialogue means no id to put in the URL. Posting anyway would 404 on
      // a `null` rendered into the path, and the reader would read that as the
      // server failing rather than as "you have not started one yet". The
      // `replying` half is the ask's reason: the server answers 409, and not
      // sending is the same answer without the round trip.
      // Read out before the guard rather than after it: `get()` is opaque to
      // the narrowing, so a second call would be `string | null` again.
      const dialogueId = get().dialogueId
      if (!trimmed || dialogueId === null || get().replying) return

      set((state) => ({
        transcript: answered(state.transcript, trimmed),
        replying: true,
        error: null,
      }))
      try {
        await dialogues.reply(projectId, dialogueId, trimmed, (event) => {
          // Intercepted rather than folded: the framing is the dialogue's, not
          // a turn's, exactly as the ask intercepts its `conversation` frame.
          // `pendingBlocks` is overwritten on every exchange because a resumed
          // dialogue sends the outstanding question here, not an opening one.
          if (event.type === 'dialogue') {
            set({
              dialogueId: event.dialogueId,
              goal: event.goal,
              stoppingCondition: event.stoppingCondition,
              pendingBlocks: event.pendingBlocks,
            })
            return
          }
          set((state) => ({ transcript: applyEvent(state.transcript, event) }))
        })
        settleOpenTurn(
          set,
          get,
          // Reached when the body stopped without a `prompt` or an `error` --
          // a dropped connection, which resolves `reply` normally. `composing`
          // is set by a `delta` frame and cleared only by those two frames, so
          // without this the turn keeps a composing indicator that never turns
          // off: on screen that is indistinguishable from a model still
          // thinking, and it never resolves. The fold is pure and cannot see a
          // stream end, so this is the only place it can be closed. The test
          // that fails without it is `settles a turn whose stream ended
          // without a question or an error`; `leaves a turn its stream
          // completed alone` is why it is conditional rather than
          // unconditional.
          'the connection closed before the dialogue asked its next question',
        )
      } catch (err) {
        const detail = errorMessage(err)
        // A failure before streaming starts (404, 409, network) arrives as a
        // rejection rather than an in-band `error` event, so this is the only
        // place that path settles the open turn.
        set((state) => ({
          transcript: applyEvent(state.transcript, { type: 'error', detail }),
          error: detail,
        }))
      } finally {
        set({ replying: false })
      }
    },
  }))

/** Closes the open turn if the stream left it open, and does nothing otherwise.
 *
 * Conditional on purpose: a turn that ended with a `prompt` is already settled,
 * and `applyEvent` ignores events on a settled turn -- so this is belt and
 * braces there rather than a second guard. Written as a check anyway because
 * the intent ("only an abandoned turn") is what a reader needs, and it does not
 * depend on the fold continuing to ignore late frames. */
const settleOpenTurn = (
  set: (fn: (state: DialogueState) => Partial<DialogueState>) => void,
  get: () => DialogueState,
  detail: string,
): void => {
  const open = get().transcript[get().transcript.length - 1]
  if (open === undefined || open.settled) return
  set((state) => ({ transcript: applyEvent(state.transcript, { type: 'error', detail }) }))
}
