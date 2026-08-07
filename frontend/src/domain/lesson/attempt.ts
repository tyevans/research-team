/** What the server said about an answer.
 *
 * Note what this type does *not* contain a way to produce: there is no
 * constructor from a score, and no field a client could fill in from what it
 * already knows. The browser genuinely cannot mark an attempt — the learner
 * projection strips the key before it leaves the server — and this type is
 * shaped so that it cannot pretend to.
 */
export interface Verdict {
  readonly correct: boolean
  readonly score: number | null
  readonly feedback: readonly string[]
  readonly rationale: string | null
  /** Which options were right, as the *server* marked them. Present only after
   *  a submission, which is why marking never appears before one. */
  readonly correctOptions: readonly number[]
  readonly blanks: readonly BlankVerdict[]
  readonly progress: ItemProgress | null
}

export interface BlankVerdict {
  readonly blank: number
  readonly correct: boolean
  readonly answer: string
}

/** The durable record of what a learner has done with one item.
 *
 * Counted by the server, not by the client: a reload, a second tab and a retry
 * all go through it, and a client-side tally would disagree with the log the
 * moment any of those happened. */
export interface ItemProgress {
  readonly attempts: number
  readonly correct: boolean
  readonly bestScore: number
  readonly lastScore: number
  readonly checked: readonly number[]
}

export const emptyProgress = (): ItemProgress => ({
  attempts: 0,
  correct: false,
  bestScore: 0,
  lastScore: 0,
  checked: [],
})

/** A learner's in-progress interaction with one widget.
 *
 * Separate from `Verdict` because it is the half the browser legitimately owns:
 * which option is selected, what is typed into a blank, which card is face up.
 * `verdict` is the half it does not — it only ever arrives from a submission.
 */
export interface AttemptState {
  readonly picked: readonly number[]
  readonly typed: Readonly<Record<number, string>>
  readonly ticked: Readonly<Record<number, boolean>>
  readonly card: number
  readonly flipped: boolean
  readonly verdict: Verdict | null
  readonly busy: boolean
  readonly error: string | null
  readonly saveError: string | null
  /** From the durable record, not from this session's answers: what a returning
   *  learner is owed is that they met this and got it right. */
  readonly attempts: number
  readonly previouslyCorrect: boolean
}

export const freshAttempt = (): AttemptState => ({
  picked: [],
  typed: {},
  ticked: {},
  card: 0,
  flipped: false,
  verdict: null,
  busy: false,
  error: null,
  saveError: null,
  attempts: 0,
  previouslyCorrect: false,
})

/** Fold a stored record back into a widget's state.
 *
 * Deliberately does *not* reconstruct a verdict panel. The record holds counts
 * and scores, not the author's feedback text, and inventing a panel out of a
 * score would put words in their mouth. What it restores is the unambiguous
 * part: which boxes are ticked, and whether this has been answered correctly
 * before. Re-answering re-earns the real verdict. */
export const withStoredProgress = (
  attempt: AttemptState,
  progress: ItemProgress,
): AttemptState => ({
  ...attempt,
  attempts: progress.attempts,
  previouslyCorrect: progress.correct,
  ticked: progress.checked.reduce<Record<number, boolean>>(
    (ticked, index) => ({ ...ticked, [index]: true }),
    { ...attempt.ticked },
  ),
})

/** Clearing an answer for another go. Keeps what the record knows — the earlier
 *  success is a fact about the learner, not about this attempt. */
export const resetAttempt = (attempt: AttemptState): AttemptState => ({
  ...attempt,
  verdict: null,
  error: null,
  picked: [],
  typed: {},
})

/** What a submission sends, per widget type. The server decides correctness;
 *  this only has to describe what the learner did. */
export type AttemptResponse = number | readonly number[] | readonly string[]

export const mcqResponse = (picked: readonly number[], multiple: boolean): AttemptResponse =>
  multiple ? [...picked].sort((a, b) => a - b) : (picked[0] ?? [])
