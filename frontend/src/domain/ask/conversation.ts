/** The ask page's transcript, as a fold over the stream.
 *
 * Pure on purpose: streaming order is the part that goes subtly wrong, and it
 * is far cheaper to get right here than through a rendered component.
 */
import type { DocumentBlock } from '@domain/lesson/document.ts'

/** `open_topic`, the tool that would have produced a `'topic'` citation, turned
 *  out to create topics rather than read them, so it was dropped from this
 *  read-only page's tool set. Nothing can emit a topic citation any more --
 *  narrowed to the one kind a server can actually send.
 */
export interface Citation {
  readonly kind: 'source'
  readonly id: string
}

export interface AskActivity {
  readonly messageId: string
  readonly kind: 'assistant' | 'tool'
  readonly payload: unknown
  readonly isError: boolean
}

export interface AskTurn {
  readonly question: string
  readonly answer: string
  /** The document blocks the model wrote alongside `answer` -- mcq, cloze,
   *  flashcards. Empty until the turn settles: deltas carry only prose, so
   *  there is nothing to show here before the `answer` frame arrives. */
  readonly blocks: readonly DocumentBlock[]
  /** Where this turn's blocks sit in the grading log, carried straight off
   *  the `answer` frame. A grading POST for one of `blocks` has to name it,
   *  and this is the only place in the transcript that value survives to. */
  readonly position: number
  readonly activity: readonly AskActivity[]
  readonly citations: readonly Citation[]
  readonly error: string | null
  /** Settled turns are closed to further events -- see `applyEvent`. */
  readonly settled: boolean
}

export type AskTranscript = readonly AskTurn[]

export type AskEvent =
  // The server's own id for this conversation, sent once as the stream's
  // first frame. Never `chatId` -- that is minted in the browser and never
  // reaches storage, so an attempt POST built from it names a conversation
  // the server has never heard of. See `AskState.conversationId`.
  | { readonly type: 'conversation'; readonly conversationId: string }
  | { readonly type: 'delta'; readonly messageId: string; readonly text: string }
  | {
      readonly type: 'message'
      readonly messageId: string
      readonly kind: 'assistant' | 'tool'
      readonly payload: unknown
      readonly isError: boolean
    }
  | {
      readonly type: 'answer'
      readonly text: string
      readonly blocks: readonly DocumentBlock[]
      readonly position: number
      readonly citations: readonly Citation[]
    }
  | { readonly type: 'error'; readonly detail: string }

export const asked = (transcript: AskTranscript, question: string): AskTranscript => [
  ...transcript,
  {
    question,
    answer: '',
    blocks: [],
    position: 0,
    activity: [],
    citations: [],
    error: null,
    settled: false,
  },
]

export const applyEvent = (transcript: AskTranscript, event: AskEvent): AskTranscript => {
  const open = transcript.length - 1
  const turn = transcript[open]
  // A settled turn is closed: a late frame belongs to nothing, and writing it
  // in would corrupt an answer the reader has already read. The `undefined`
  // arm is the empty transcript -- an event before any question was asked.
  if (turn === undefined || turn.settled) return transcript

  const replaced = (next: AskTurn): AskTranscript => [
    ...transcript.slice(0, open),
    next,
    ...transcript.slice(open + 1),
  ]

  switch (event.type) {
    // Carries no per-turn data -- the store reads this one directly off the
    // stream to learn its conversation id, and the transcript fold has
    // nothing to do with it. Handled here only so the switch stays exhaustive.
    case 'conversation':
      return transcript
    case 'delta':
      return replaced({ ...turn, answer: turn.answer + event.text })
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
    case 'answer':
      // Replaced, not appended: the deltas already carried these same words,
      // and appending would render the answer twice.
      return replaced({
        ...turn,
        answer: event.text,
        blocks: event.blocks,
        position: event.position,
        citations: event.citations,
        settled: true,
      })
    case 'error':
      return replaced({ ...turn, error: event.detail, settled: true })
  }
}
