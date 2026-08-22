/** A course-authoring run, while it is running.
 *
 * Nothing durable records that a run started — what the log holds is the
 * `write_file` calls its turns make — so this is a view of server memory, and
 * a reload after the server restarts loses it. That is why `current` and
 * `last` are both carried: a tab that arrived mid-run and one that arrived
 * after it finished need different answers, and neither can reconstruct the
 * other's from the file list.
 */

export interface AuthoringFailure {
  readonly target: string
  readonly detail: string
}

export interface AuthoringRun {
  readonly runId: string
  /** `running`, `done` or `failed`, as a plain string.
   *
   * Not a union: a build that met a fourth value should render it rather than
   * refuse the response, and nothing here branches on it in a way a new value
   * would break. `isRunning` below is the one predicate, and it tests for the
   * one status whose meaning this client depends on. */
  readonly status: string
  readonly kind: string
  readonly targets: readonly string[]
  readonly completed: readonly string[]
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

export const isRunning = (status: AuthoringStatus): boolean =>
  status.current !== null && status.current.status === 'running'

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
