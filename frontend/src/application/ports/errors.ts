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

/** This instance was not wired for autonomous research at all.
 *
 * Distinct from "nothing is running", which the API expresses with the same
 * 404. Worth saying once and never asking about again — polling a feature that
 * is switched off is noise on somebody's log.
 *
 * Here rather than beside the adapter that raises it, even though only the HTTP
 * repository ever constructs one, because the *other* end of this class is a
 * component: `RunPanel` branches on it to decide between a panel and a notice.
 * `ResearchRepository.current` already promises this rejection in its own
 * docstring, so the port's contract named a class the port did not own — and
 * presentation had to reach into `infrastructure/http` to honour it. Moving the
 * class is what lets both sides depend on the port instead of on each other;
 * the cost is that an error with no transport in it now sits in a file whose
 * other two members are about the wire, which is the smaller wrong. */
export class ResearchDisabledError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ResearchDisabledError'
  }
}

export const errorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : String(error)
