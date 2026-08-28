/** A failure from the API, carrying the one thing callers branch on.
 *
 * The status code is not incidental here — four separate places in this
 * application make a *domain* decision from it: a 404 on a file means "not
 * written yet at this point", which is information rather than a failure; a 404
 * on the run route means either "nothing running" or "this feature is off"; a
 * 409 on a turn means somebody else is mid-turn; and a 499 means a turn was
 * cancelled on purpose, which is an outcome and not an error. Losing the status
 * in a plain `Error` is what forced those decisions to be made by matching on
 * message text.
 */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  /** The path does not exist at the point that was asked about. */
  get isNotFound(): boolean {
    return this.status === 404
  }

  /** A turn is already running on this session. */
  get isConflict(): boolean {
    return this.status === 409
  }

  /** Closed by the client on purpose. Not a failure — no red, no toast. */
  get isCancelled(): boolean {
    return this.status === 499
  }
}

/** A response that did not match the shape this build expects.
 *
 * Kept distinct from `ApiError` because the remedies differ completely: an
 * `ApiError` is usually worth retrying and a contract mismatch never is. */
export class ContractError extends Error {
  constructor(
    message: string,
    readonly detail: string,
  ) {
    super(message)
    this.name = 'ContractError'
  }
}

export const errorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : String(error)
