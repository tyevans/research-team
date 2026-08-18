/** A dialogue's transcript, as a fold over the stream.
 *
 * A sibling of `ask/conversation.ts` and deliberately not a reuse of it. The
 * two surfaces run in opposite directions: an ask is reader-asks /
 * agent-answers, a dialogue is agent-asks / reader-answers. A transcript type
 * shared between them would make that inversion a runtime concern, and a view
 * that drew it the wrong way round would still look like a conversation --
 * just one where the reader asks all the questions. Nothing but an explicit
 * assertion notices, which is why the tests check both which field holds which
 * text and which one opens the turn.
 *
 * **A turn pairs `(reply, blocks)`** -- the reader's answer and the question it
 * PRODUCED, not the question it answered. The question the reader was answering
 * when they opened the first turn is the dialogue row's opening one and lives
 * on the store, not here.
 *
 * **The question is `blocks` and never a string, and deltas never touch it.**
 * No server surface carries a raw prompt -- `_socratic_frame` dropped its
 * `text` key when the answer key was found shipping beside the projection --
 * so a turn's question is the projection or nothing. The `delta` frames still
 * have a `text` field, and folding it into the question would render the key
 * on screen for the moment before the `prompt` frame replaced it, the day
 * anything refills it. They drive `composing` and nothing else.
 *
 * `AskActivity` and `Citation` are imported rather than redeclared: activity is
 * activity, and the citation kinds are the server's, not this surface's.
 */
import type { AskActivity, Citation } from '@domain/ask/conversation.ts'
import type { DocumentBlock } from '@domain/lesson/document.ts'

/** `AskActivity` with one more `kind`, rather than a second copy of it.
 *
 * `remark` is a kind the ask never sees: an `ActivityRemark` has no
 * `message_id` by design, so Plan 2 sends it as a message with an empty one so
 * a page can style it apart from a model utterance without a sixth frame type.
 * A union copied straight from `AskActivity` drops it -- the test that would
 * fail is `keeps activity, including a remark, in arrival order`. */
export interface DialogueActivity extends Omit<AskActivity, 'kind'> {
  readonly kind: 'assistant' | 'tool' | 'remark'
}

export interface DialogueTurn {
  /** What the dialogue asked. Blocks, never a string -- no surface carries a
   *  raw prompt. */
  readonly blocks: readonly DocumentBlock[]
  /** What the reader answered. Raw, because it is their own words. */
  readonly reply: string
  /** Where this turn's blocks sit in the dialogue's grading log, carried
   *  straight off the `prompt` frame. An attempt POST for one of `blocks` has
   *  to name it, and this is the only place it survives to. */
  readonly position: number
  readonly activity: readonly DialogueActivity[]
  readonly citations: readonly Citation[]
  readonly concluded: boolean
  readonly error: string | null
  /** Settled turns are closed to further events -- see `applyEvent`. */
  readonly settled: boolean
  /** Whether the dialogue is mid-utterance right now.
   *
   * A field rather than `activity.length > 0`, which is the derivation someone
   * will reach for. A turn whose model ran a tool and then went quiet has
   * activity and is *not* composing, and the two states look different on
   * screen: one says "reading the corpus", the other says "writing". Deriving
   * it would leave the composing indicator stuck on for the whole of a long
   * tool call and then never turn off, which reads as a hang.
   *
   * Set by `delta` frames and cleared when the turn settles. The text those
   * frames carry never reaches the page -- see this module's docstring. */
  readonly composing: boolean
}

export type DialogueTranscript = readonly DialogueTurn[]

export type DialogueEvent =
  // The dialogue's identity and its pending question, sent once as the
  // stream's first frame. The store reads it; a turn has nothing to do with
  // it, because the pending question belongs to the row and not to any turn.
  | {
      readonly type: 'dialogue'
      readonly dialogueId: string
      readonly goal: string
      readonly stoppingCondition: string
      readonly pendingBlocks: readonly DocumentBlock[]
    }
  // `text` is EMPTY on every real frame today -- `_socratic_frame` empties it
  // rather than dropping the frame, so the liveness signal survives without
  // the leak. Typed anyway, because the field is on the wire and a fold that
  // reads it is the defect this module is shaped to prevent.
  | { readonly type: 'delta'; readonly messageId: string; readonly text: string }
  | {
      readonly type: 'message'
      readonly messageId: string
      readonly kind: 'assistant' | 'tool' | 'remark'
      readonly payload: unknown
      readonly isError: boolean
    }
  // Typed `prompt` and not `answer` because it is a question. There is no
  // `text` key beside `blocks` and its absence is load-bearing: the raw copy
  // shipped the fenced component with `correct: true` in it while the
  // projection one key to its right withheld exactly that.
  | {
      readonly type: 'prompt'
      readonly blocks: readonly DocumentBlock[]
      readonly position: number
      readonly citations: readonly Citation[]
      readonly concluded: boolean
    }
  | { readonly type: 'error'; readonly detail: string }

/** `answered` and not `asked`: on this surface the reader's move opens a turn. */
export const answered = (transcript: DialogueTranscript, reply: string): DialogueTranscript => [
  ...transcript,
  {
    blocks: [],
    reply,
    // `-1` and not `0`, which is what this opened at: an open turn has no
    // position until its `prompt` frame lands, and `0` is a real one. A second
    // turn in flight was therefore handed `progress['turn/0']` -- the FIRST
    // turn's verdicts, against a question it is not asking. Harmless only
    // because an open turn has empty `blocks` and so renders no widget to
    // mis-mark; that is a property of `DialogueThread`'s rendering, not of
    // this fold, and it is one refactor away from being untrue. `-1` names no
    // turn the server can have graded, so the lookup misses, which is the
    // honest answer for a turn nobody has answered yet.
    position: -1,
    activity: [],
    citations: [],
    concluded: false,
    error: null,
    settled: false,
    composing: false,
  },
]

export const applyEvent = (
  transcript: DialogueTranscript,
  event: DialogueEvent,
): DialogueTranscript => {
  const open = transcript.length - 1
  const turn = transcript[open]
  // A settled turn is closed: a late frame belongs to nothing, and writing it
  // in would overwrite a question the reader has already read. The `undefined`
  // arm is the empty transcript -- a frame that arrived before the reader
  // answered anything.
  if (turn === undefined || turn.settled) return transcript

  const replaced = (next: DialogueTurn): DialogueTranscript => [
    ...transcript.slice(0, open),
    next,
    ...transcript.slice(open + 1),
  ]

  switch (event.type) {
    case 'dialogue':
      return transcript
    // Appends nothing. `event.text` is read nowhere in this module and that is
    // the point -- see the module docstring.
    case 'delta':
      return replaced({ ...turn, composing: true })
    case 'message':
      return replaced({
        ...turn,
        activity: [
          ...turn.activity,
          {
            messageId: event.messageId,
            kind: event.kind,
            payload: event.payload,
            isError: event.isError,
          },
        ],
      })
    case 'prompt':
      return replaced({
        ...turn,
        blocks: event.blocks,
        position: event.position,
        citations: event.citations,
        concluded: event.concluded,
        settled: true,
        composing: false,
      })
    case 'error':
      return replaced({ ...turn, error: event.detail, settled: true, composing: false })
  }
}

/** Whether the dialogue is composing its next question right now.
 *
 * Reads the open turn's flag. An empty transcript is not composing: nothing
 * has been asked of the model yet. */
export const composing = (transcript: DialogueTranscript): boolean =>
  transcript[transcript.length - 1]?.composing ?? false
