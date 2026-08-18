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
 *    `stoppingCondition` and `openingBlocks` are the dialogue's framing, not
 *    turns in it; a transcript that held them would draw them as something the
 *    reader has to answer.
 * 3. **The store settles a stream that ended without settling itself.** The
 *    fold is pure and cannot see a body stop.
 */
import { create } from 'zustand'

import { errorMessage } from '@application/ports/errors.ts'
import type { DialogueProgress, DialogueRepository } from '@application/ports/repositories.ts'
import { answered, applyEvent, type DialogueTranscript } from '@domain/dialogue/conversation.ts'
import type { DocumentBlock } from '@domain/lesson/document.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

export interface DialogueState {
  readonly transcript: DialogueTranscript
  readonly dialogueId: string | null
  readonly goal: string
  readonly stoppingCondition: string
  /** The question that OPENED the dialogue -- the one belonging to no turn.
   *
   * Framing rather than a turn, which is why it is here beside `goal` and not
   * captured in the view: a view holding it would need its own ref and would
   * lose it on remount. Blocks, never a string.
   *
   * Captured from the first `dialogue` frame and never overwritten. The frame's
   * `pending_blocks` is "the question being answered, not the one about to be
   * asked" (`app.py:3117`), so on exchange N it is turn N-1's question -- which
   * is already on screen. Only on the FIRST exchange does it name a question no
   * turn carries, and that is the opening one. Overwriting it, as this store
   * did, walked the opening question forward and drew a duplicate of a
   * question one exchange stale at the top of the thread. */
  readonly openingBlocks: readonly DocumentBlock[]
  /** What this reader has already had marked in this dialogue, keyed
   *  `turn/{position}`.
   *
   * The state that makes this surface's claim true rather than merely
   * recorded: an attempt is written against the dialogue id, and until
   * `refreshProgress` existed nothing read it back, so a refresh showed blank
   * widgets over answers the server remembered perfectly. Empty until the
   * first refresh resolves, which is honest -- an unanswered widget and an
   * unloaded one look the same because at that moment they are the same
   * thing to the reader. */
  readonly progress: DialogueProgress
  /** Whether the last progress load failed.
   *
   * Not an error banner, and deliberately not routed into `error`: this call
   * is not the reader's action, so blaming their last answer for a request
   * they did not make is worse than silence. It is a flag rather than nothing
   * because once a dialogue is resumable this path is reachable in the case
   * the whole route exists for -- a reader coming back to answers the server
   * remembers -- and a silent failure there is indistinguishable from a
   * dialogue that forgot.
   *
   * What it costs: one quiet line beside the thread that a reader can do
   * nothing about, on a page where every other pixel is the dialogue. What
   * NOT having it cost: nothing at all on screen, which is why the swallow
   * below stood for a whole plan. Cleared on the next successful load, so a
   * transient failure does not stick. */
  readonly progressUnavailable: boolean
  readonly replying: boolean
  readonly starting: boolean
  readonly error: string | null
  start(topic: string): Promise<void>
  send(reply: string): Promise<void>
  /** Reloads the marked answers. Called on mount and after an attempt is
   *  marked, and never on a null `dialogueId`. */
  refreshProgress(): Promise<void>
}

export type DialogueStore = ReturnType<typeof createDialogueStore>

export const createDialogueStore = ({
  dialogues,
  projectId,
  /** The dialogue already in the URL, or `null` for "the reader has not
   *  started one".
   *
   * The whole of what makes a dialogue resumable. Without it the store began
   * every mount at `null`, `refreshProgress` short-circuited on its own guard,
   * and the only dialogue that could exist in a browser was one just minted
   * with no attempts in it -- so `progress` could only ever be `{}`, and a
   * refresh lost not the grades but the entire dialogue. Every hop beneath
   * this one was correct and proved; the gap was navigation alone.
   *
   * A seed rather than a subscription: the id changes exactly once per store,
   * from null to the minted one, and `DialogueView` rebuilds the store when
   * the URL names a DIFFERENT dialogue. */
  dialogueId = null,
}: {
  dialogues: DialogueRepository
  projectId: ProjectId
  dialogueId?: string | null
}) =>
  create<DialogueState>((set, get) => ({
    transcript: [],
    dialogueId,
    goal: '',
    stoppingCondition: '',
    openingBlocks: [],
    progress: {},
    progressUnavailable: false,
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
        // The framing arrives HERE, with the id, and that is the whole of what
        // this fold buys. It used to take an id alone, so a freshly framed
        // dialogue drew "Pick something to work through." over an empty thread
        // -- the goal, the stopping condition and the opening question all
        // existed on the server and none of them were on screen until the
        // reader answered a question they could not see. The test that fails
        // if this narrows back to an id is `draws the framing the moment the
        // dialogue is framed`.
        const framing = await dialogues.start(projectId, trimmed)
        set({
          dialogueId: framing.dialogueId,
          goal: framing.goal,
          stoppingCondition: framing.stoppingCondition,
          openingBlocks: framing.openingBlocks,
        })
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
          if (event.type === 'dialogue') {
            set((state) => ({
              dialogueId: event.dialogueId,
              goal: event.goal,
              stoppingCondition: event.stoppingCondition,
              // First frame only -- see `openingBlocks` for why a later
              // frame's blocks are a question already drawn.
              openingBlocks:
                state.openingBlocks.length > 0 ? state.openingBlocks : event.pendingBlocks,
            }))
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

    async refreshProgress() {
      const dialogueId = get().dialogueId
      // Read out before the guard rather than after it, as `send` does: `get()`
      // is opaque to the narrowing, so a second call would be `string | null`
      // again. No dialogue means no id for the path, and a `null` rendered
      // into it 404s.
      if (dialogueId === null) return
      try {
        set({
          progress: await dialogues.progress(projectId, dialogueId),
          progressUnavailable: false,
        })
      } catch {
        set({ progressUnavailable: true })
        // Swallowed, and this is the one place in this store that swallows.
        // The others surface because they are the reader's own action failing;
        // this one runs unbidden on mount and after every marked answer, and
        // the widget it feeds already shows its own verdict from the attempt
        // response. Turning a failed background reload into the page's `error`
        // banner would blame the reader's last answer for a request they did
        // not make. The cost, stated plainly: a progress load that fails
        // repeatedly is invisible, and what it looks like is a dialogue that
        // forgot -- which is the bug this whole route exists to fix. So the
        // failure sets `progressUnavailable` instead, which the page draws as
        // one quiet line near the thread rather than as a banner. The test
        // that fails without the flag is `says so quietly when the answers
        // could not be loaded`.
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
