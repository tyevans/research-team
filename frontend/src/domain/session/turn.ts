import type { EventIndex } from './event-index.ts'

/** The span of log a completed turn wrote, as the turn itself reported it.
 *
 * Taken from the POST's response rather than diffed against the log we held,
 * because a turn is atomic: its whole span appears at once, and the log we held
 * may already have been overtaken by another tab's turn. */
export interface TurnRange {
  readonly turnIndex: number | null
  readonly from: EventIndex
  readonly to: EventIndex
}

/** A turn running on this session that this tab did not start.
 *
 * `from` is filled by the first frame seen after it began — its
 * `UserMessageSent` — because nothing else on the wire says where a foreign
 * turn opened. It stays null until that frame arrives. */
export interface WatchedTurn {
  readonly turnIndex: number | null
  readonly startedAt: string | null
  readonly elapsedSeconds: number | null
  readonly from: EventIndex | null
}

/** What the composer is doing.
 *
 * Three states, and the distinction between the middle two is the one the
 * previous implementation carried in two booleans that had to be read together
 * everywhere: `sending` is a turn *this tab* posted and is awaiting a response
 * for; `watching` is a turn somebody else started, which this tab learns about
 * from the stream and can only observe. They disable the same controls and say
 * completely different things, and only `sending` gets a 499 to interpret.
 */
export type TurnState =
  | { readonly status: 'idle' }
  | { readonly status: 'sending'; readonly startedAt: number; readonly cancelRequested: boolean }
  | { readonly status: 'watching'; readonly turn: WatchedTurn; readonly cancelRequested: boolean }

const IDLE: TurnState = Object.freeze({ status: 'idle' as const })

export const TurnState = {
  idle: (): TurnState => IDLE,

  sending: (startedAt: number): TurnState => ({
    status: 'sending',
    startedAt,
    cancelRequested: false,
  }),

  watching: (turn: WatchedTurn): TurnState => ({
    status: 'watching',
    turn,
    cancelRequested: false,
  }),

  /** Both busy states disable the composer; only the wording differs. */
  isBusy: (state: TurnState): boolean => state.status !== 'idle',

  /** Whether this tab owns the in-flight POST, and so owns its outcome. */
  isOurs: (state: TurnState): boolean => state.status === 'sending',

  /** Whether a cancel has already been asked for. Idle can never have one
   *  outstanding, which is why this is a question rather than a field read. */
  isCancelRequested: (state: TurnState): boolean =>
    state.status !== 'idle' && state.cancelRequested,

  withCancelRequested: (state: TurnState): TurnState =>
    state.status === 'idle' ? state : { ...state, cancelRequested: true },

  /** The first frame of a watched turn tells us where it opened. */
  withWatchedOrigin: (state: TurnState, from: EventIndex): TurnState =>
    state.status === 'watching' && state.turn.from === null
      ? { ...state, turn: { ...state.turn, from } }
      : state,
} as const

/** The outcome of the last turn, shown beside the composer until it is stale.
 *
 * `tone` is deliberately not derived from the text: a cancellation is `calm`
 * and a failure is `warn`, and a cancelled turn arriving as a `TurnFailed` is
 * exactly the case where reading the type would get it wrong.
 */
export interface TurnNote {
  readonly tone: 'good' | 'warn' | 'calm'
  readonly text: string
  readonly range: TurnRange | null
  /** Offers a "re-check" affordance: the note is a guess, not an observation. */
  readonly recheck: boolean
}

export const turnNote = (
  tone: TurnNote['tone'],
  text: string,
  options: { range?: TurnRange | null; recheck?: boolean } = {},
): TurnNote => ({
  tone,
  text,
  range: options.range ?? null,
  recheck: options.recheck ?? false,
})
