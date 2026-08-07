import type { ProjectId, RunId, SessionId } from '../shared/identifier.ts'

/** An autonomous run over a project's topic queue: one round is one topic and
 *  one turn.
 *
 * The whole point of this model is to make two things impossible to confuse — a
 * run that is going, and a run that has stopped — and to keep "stopped" from
 * reading as "finished". A run cannot decide it is done; every ending is a fold
 * of its own stream or of the queue, and only one of them means the work in
 * front of it ran out.
 */
export interface ResearchRun {
  readonly runId: RunId
  readonly projectId: ProjectId
  /** Where the work is actually visible: the rounds are turns on this session,
   *  and counters here are only the shape of it. */
  readonly sessionId: SessionId
  readonly progress: RunProgress | null
}

export interface RunProgress {
  readonly status: 'new' | 'running' | 'stopped' | (string & {})
  readonly rounds: number
  readonly turns: number
  /** Counted by folding the topic before and after the turn, not by reading the
   *  reply: a round that describes a breakthrough and records nothing is an
   *  empty round. */
  readonly findings: number
  readonly stopReason: StopReasonCode | null
  /** A topic whose round began and has not ended. */
  readonly workingOn: string | null
  readonly quietRounds: number
  readonly failures: number
  readonly budget: { readonly maxRounds: number | null; readonly quietRounds: number | null }
  /** Under a policy that floors `fetch` at `ask`, so it works from material
   *  already in hand rather than deadlocking on an approval nobody will answer. */
  readonly readOnly: boolean
}

export type StopReasonCode =
  | 'queue_empty'
  | 'max_rounds'
  | 'budget_exhausted'
  | 'no_new_findings'
  | 'error_rate'
  | 'cancelled'
  | (string & {})

/** A run with no progress at all is the 202 body — ids only, no fold yet. It
 *  has begun, so it counts as live: the alternative is one frame of "ended,
 *  reason unknown" between starting a run and the first poll. */
export const isLive = (run: ResearchRun | null): boolean => {
  if (!run) return false
  if (run.progress === null) return true
  return run.progress.status === 'running' || run.progress.status === 'new'
}

export type EndingTone = 'done' | 'short' | 'bad'

export interface Ending {
  readonly tone: EndingTone
  readonly label: string
  readonly headline: string
  readonly text: string
}

/** How a run ended, said in words rather than left as an enum value.
 *
 * `tone` is the load-bearing part: a reader who skims a green box takes away
 * "done", and exactly one of these endings has earned that. The rest describe a
 * run that stopped with topics still on the queue, which is not success and
 * must not be dressed as it.
 */
const ENDINGS: Readonly<Record<string, Ending>> = {
  queue_empty: {
    tone: 'done',
    label: 'queue empty',
    headline: 'Nothing left on the queue.',
    text:
      'The queue had nothing left to claim. This is the only ending that means ' +
      'the work in front of the run ran out.',
  },
  max_rounds: {
    tone: 'short',
    label: 'round cap reached',
    headline: 'Stopped with work still in front of it.',
    text: 'It spent the rounds it was given. The queue was not empty when it stopped.',
  },
  budget_exhausted: {
    tone: 'short',
    label: 'budget spent',
    headline: 'Stopped with work still in front of it.',
    text: 'Its budget ran out before the queue did.',
  },
  no_new_findings: {
    tone: 'short',
    label: 'went quiet',
    headline: 'Stopped with work still in front of it.',
    text:
      'Consecutive rounds recorded nothing, so it stopped rather than keep spending. ' +
      'Quiet is not the same as finished — the topics it went quiet on are still on the queue.',
  },
  error_rate: {
    tone: 'bad',
    label: 'too many failures',
    headline: 'Stopped with work still in front of it.',
    text:
      'Consecutive turns failed. Nothing here says the remaining work is done; ' +
      'it says the run could not do it.',
  },
  cancelled: {
    tone: 'short',
    label: 'cancelled',
    headline: 'Stopped with work still in front of it.',
    text:
      'Somebody asked it to stop, and it stopped after the round it was in. ' +
      'Whatever was still queued is still queued.',
  },
}

export const endingFor = (reason: StopReasonCode | null | undefined): Ending =>
  ENDINGS[String(reason ?? '')] ?? {
    tone: 'short',
    label: String(reason ?? 'unknown'),
    headline: 'Stopped with work still in front of it.',
    // An ending this build does not know is still an ending. The safe reading
    // of an unrecognised one is the un-finished one.
    text:
      'This build does not recognise that ending, so treat it as a run that stopped ' +
      'rather than one that finished.',
  }

/** A run that left the live route between polls without an ending anybody read.
 *
 * Saying so is the honest reading; clearing back to "no run" would quietly
 * retract an ending nobody got to see. */
export const ENDING_NOT_SEEN: Ending = {
  tone: 'short',
  label: 'ending not seen',
  headline: 'It ended; this page did not see how.',
  text:
    'The run left the live route between polls, so this page never read why it stopped. ' +
    'Its rounds are turns on its session, and the stop is recorded on its own stream there.',
}

/** The optional round cap, as typed into a browser.
 *
 * Sending nothing is a real choice rather than a missing value: it means the
 * run is under the domain's own budget. So an empty string is valid and a
 * nonsense one is not, and the two need telling apart. */
export type RoundCap =
  | { readonly kind: 'domainBudget' }
  | { readonly kind: 'capped'; readonly rounds: number }
  | { readonly kind: 'invalid'; readonly reason: string }

export const parseRoundCap = (typed: string): RoundCap => {
  const trimmed = typed.trim()
  if (!trimmed) return { kind: 'domainBudget' }
  const rounds = Number.parseInt(trimmed, 10)
  if (!Number.isInteger(rounds) || rounds < 1) {
    return { kind: 'invalid', reason: 'Max rounds must be a whole number of at least 1.' }
  }
  return { kind: 'capped', rounds }
}
