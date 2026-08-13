/** The ask page's transcript, as a fold over the stream.
 *
 * Pure on purpose: streaming order is the part that goes subtly wrong, and it
 * is far cheaper to get right here than through a rendered component.
 */

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
  readonly activity: readonly AskActivity[]
  readonly citations: readonly Citation[]
  readonly error: string | null
  /** Settled turns are closed to further events -- see `applyEvent`. */
  readonly settled: boolean
}

export type AskTranscript = readonly AskTurn[]

export type AskEvent =
  | { readonly type: 'delta'; readonly messageId: string; readonly text: string }
  | {
      readonly type: 'message'
      readonly messageId: string
      readonly kind: 'assistant' | 'tool'
      readonly payload: unknown
      readonly isError: boolean
    }
  | { readonly type: 'answer'; readonly text: string; readonly citations: readonly Citation[] }
  | { readonly type: 'error'; readonly detail: string }

export const asked = (transcript: AskTranscript, question: string): AskTranscript => [
  ...transcript,
  { question, answer: '', activity: [], citations: [], error: null, settled: false },
]

export const applyEvent = (transcript: AskTranscript, event: AskEvent): AskTranscript => {
  const open = transcript.length - 1
  // A settled turn is closed: a late frame belongs to nothing, and writing it
  // in would corrupt an answer the reader has already read.
  if (open < 0 || transcript[open].settled) return transcript

  const turn = transcript[open]
  const replaced = (next: AskTurn): AskTranscript => [
    ...transcript.slice(0, open),
    next,
    ...transcript.slice(open + 1),
  ]

  switch (event.type) {
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
        citations: event.citations,
        settled: true,
      })
    case 'error':
      return replaced({ ...turn, error: event.detail, settled: true })
  }
}
