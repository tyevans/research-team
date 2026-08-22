/** A course-authoring run: what it is doing, or what it did.
 *
 * **This comment used to say the run was memory-only, and that was the bug.**
 * A run's targets and the session id holding each authored course are now on
 * the log, projected into a table, and survive a restart — which is what makes
 * `courseLinks` below worth anything at all: it is the only route back to the
 * markdown a run wrote, and it used to be lost every time the server bounced.
 *
 * What is still memory-only is `current` — which area is being written this
 * minute. Nothing is driving a run whose process is gone, so the server reports
 * `null` for it on any run it did not start itself.
 *
 * `current` and `last` are both carried because a tab that arrived mid-run and
 * one that arrived after it finished need different answers, and neither can
 * reconstruct the other's from the file list.
 */

export interface AuthoringFailure {
  readonly target: string
  readonly detail: string
}

export interface AuthoringRun {
  readonly runId: string
  /** `running`, `done`, `failed`, `cancelled` or `interrupted`, as a plain
   * string.
   *
   * Not a union: a build that met a sixth value should render it rather than
   * refuse the response, and nothing here branches on it in a way a new value
   * would break. The predicates below are the only readers, and each tests for
   * one status whose meaning this client depends on.
   *
   * The last two are the ones worth telling apart. `cancelled` is a person
   * having pressed stop; `interrupted` is a run that was still going when the
   * server died and that nothing is driving any more. Both leave a partial set
   * of courses behind — which is exactly why folding either into `failed`
   * would tell a reader that courses which exist were never written. */
  readonly status: string
  readonly kind: string
  readonly targets: readonly string[]
  readonly completed: readonly string[]
  /** One session id per completed target, in `completed`'s order.
   *
   * Load-bearing rather than diagnostic: each authoring run writes into its own
   * session's workspace, so this is the *only* way back to the files it wrote.
   * Read through `courseLinks` and never index-matched by hand -- see there. */
  readonly sessions: readonly string[]
  /** The area being authored right now, or `null` between and after them.
   *
   * The field that makes a long run legible. A run over eight areas is up to
   * twenty-four model turns and can sit at "running" for a very long time; a
   * panel that could only say "running" for twenty minutes is indistinguishable
   * from one that has hung. */
  readonly current: string | null
  /** Per-target failures. A run that authored seven of eight areas is `done`
   *  with one failure listed, not `failed` — calling it failed would hide
   *  seven courses that exist. */
  readonly failures: readonly AuthoringFailure[]
}

export interface AuthoringStatus {
  readonly current: AuthoringRun | null
  readonly last: AuthoringRun | null
}

export const noAuthoring: AuthoringStatus = { current: null, last: null }

/** Where each finished course can be read: one target, one session.

 * Zips two parallel arrays, and refuses to guess when they disagree. A run
 * whose `sessions` is shorter than its `completed` -- an older server, a frame
 * from before the field existed -- yields the pairs it can and drops the rest,
 * rather than pairing a target with the wrong run's session. A link to the
 * wrong course is worse than no link: it opens something real, so nobody
 * suspects it.
 */
export const courseLinks = (
  run: AuthoringRun,
): readonly { readonly target: string; readonly sessionId: string }[] =>
  run.completed
    .map((target, index) => ({ target, sessionId: run.sessions[index] ?? null }))
    .filter((pair): pair is { target: string; sessionId: string } => pair.sessionId !== null)

export const isRunning = (status: AuthoringStatus): boolean =>
  status.current !== null && status.current.status === 'running'

/** Whether the last run ended because somebody stopped it.
 *
 * Separate from `endedIncomplete` below because the two want different words
 * on screen: "stopped" is an outcome the reader chose, and reporting it in the
 * same breath as a crash reads as though the button broke something. */
export const wasCancelled = (run: AuthoringRun): boolean => run.status === 'cancelled'

/** Whether the last run stopped short of its targets, for any reason.
 *
 * True for `cancelled`, `interrupted` and a `failed` run alike. What it is
 * *not* true for is a `done` run carrying per-target failures: that run reached
 * the end of its list, and the failures it names are already rendered beside
 * it. The distinction matters because this is what decides whether the panel
 * says how many targets were never attempted. */
export const endedIncomplete = (run: AuthoringRun): boolean =>
  run.status !== 'running' && run.completed.length + run.failures.length < run.targets.length

/** How the last run ended, in words, or `null` for an ordinary finish.
 *
 * `null` rather than "done" for the ordinary case: the panel already says how
 * many of how many were written, and a label repeating "done" beside it is
 * noise on the ninety-nine runs that went fine.
 *
 * `interrupted` is spelled out rather than shortened, because it is the one
 * status a reader has no way to guess the meaning of — it is not something
 * they did and not something the model did. */
export const endingOf = (run: AuthoringRun): string | null => {
  if (run.status === 'cancelled') return 'stopped'
  if (run.status === 'interrupted') return 'interrupted by a restart'
  if (run.status === 'failed') return 'failed'
  return null
}

/** How far a run has got, as a fraction, or `null` when it has no targets.
 *
 * `null` rather than 0 for an empty run, and the distinction is the one a
 * progress bar gets wrong: a bar at 0% asserts that work is pending, and a run
 * with nothing to do has none. The server refuses to start such a run at all
 * (409), so this should be unreachable — it is here because a bar that divides
 * by zero renders `NaN%` rather than failing, which is the failure that
 * survives to production.
 */
export const progressOf = (run: AuthoringRun): number | null =>
  run.targets.length === 0 ? null : run.completed.length / run.targets.length
