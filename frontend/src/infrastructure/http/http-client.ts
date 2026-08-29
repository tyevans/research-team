import type { z } from 'zod'

import { ApiError, ContractError } from '@application/ports/errors.ts'

/** The one place that speaks HTTP.
 *
 * Two responsibilities and no more: turn a non-2xx into an `ApiError` carrying
 * its status, and validate the body against the schema the caller expects.
 * Everything above this line works in domain terms.
 *
 * Validation is not ceremony here. The console renders a backend it is
 * versioned separately from, and an unchecked `as` would turn a renamed field
 * into `undefined` propagating silently into a row that renders blank. A
 * `ContractError` names the field and the endpoint instead.
 */
export class HttpClient {
  constructor(
    private readonly baseUrl: string = '',
    /** Called once for the first 401 this client sees, and never again.
     *
     * A seam rather than a `location.assign` inline, so that a test can drive
     * the behaviour and so that the transport still does exactly two things --
     * the class docstring above is the contract, and "redirect the browser" is
     * not one of them.
     *
     * **Why once.** A console page issues many requests in parallel, and a
     * cookie that expired between two of them fails all of them. Without a
     * latch every one of those would call the handler, which in production
     * assigns `location` -- so the browser is told to navigate five or ten
     * times in the same tick. Chromium tolerates that and Firefox has
     * historically not; either way it is a navigation storm produced by one
     * expiry.
     *
     * The 401 is *still thrown* after the handler runs. Swallowing it would
     * leave every caller awaiting a promise that never settles, and a page
     * that hangs with no error while a navigation may or may not happen is
     * worse than an error box that is about to be replaced anyway.
     */
    private readonly onUnauthorized?: () => void,
  ) {}

  /** The latch for `onUnauthorized`. An instance field rather than a module
   *  one, so two clients (a test's and the app's) cannot silence each other. */
  private reportedUnauthorized = false

  // Generic over the *schema* rather than over a result type: several of these
  // shapes carry transforms, so their input and output types differ, and
  // `z.ZodType<T>` would unify both onto T and silently hand back the input.
  get<S extends z.ZodTypeAny>(path: string, schema: S): Promise<z.output<S>> {
    return this.request('GET', path, undefined, schema)
  }

  post<S extends z.ZodTypeAny>(path: string, body: unknown, schema: S): Promise<z.output<S>> {
    return this.request('POST', path, body ?? {}, schema)
  }

  patch<S extends z.ZodTypeAny>(path: string, body: unknown, schema: S): Promise<z.output<S>> {
    return this.request('PATCH', path, body ?? {}, schema)
  }

  /** The settings write. Separate from `post` rather than folded into it
   *  because the settings routes are the console's first idempotent
   *  full-replacement writes — `PUT /api/settings/{scope}/{id}/{key}` may be
   *  sent twice and means the same thing, which `POST` does not promise — and
   *  a repository that reached for `post` there would be describing the route
   *  wrongly to anyone reading it. */
  put<S extends z.ZodTypeAny>(path: string, body: unknown, schema: S): Promise<z.output<S>> {
    return this.request('PUT', path, body ?? {}, schema)
  }

  delete<S extends z.ZodTypeAny>(path: string, schema: S): Promise<z.output<S>> {
    return this.request('DELETE', path, undefined, schema)
  }

  /** A multipart POST, for bytes rather than JSON.
   *
   * Its own method rather than `post` accepting a `FormData`, because the two
   * differ in the header that must *not* be set: the browser writes
   * `Content-Type: multipart/form-data; boundary=...` itself, and a
   * hand-written one loses the boundary and the server parses nothing. Sharing
   * `request` would mean a conditional in the one place that is deliberately
   * unconditional, so the body handling is duplicated here and the response
   * handling is not.
   */
  async postForm<S extends z.ZodTypeAny>(
    path: string,
    body: FormData,
    schema: S,
  ): Promise<z.output<S>> {
    const response = await fetch(this.url(path), {
      method: 'POST',
      headers: { Accept: 'application/json' },
      body,
    })
    return this.decode('POST', path, response, schema)
  }

  /** The absolute URL for a path, for the cases where the browser does the
   *  fetching: a `<video src>` or an `<img src>` is a request this class never
   *  makes, and the base url it would have prefixed lives here. Public so a
   *  repository can hand one out without a second copy of `baseUrl`. */
  url(path: string): string {
    return `${this.baseUrl}${path}`
  }

  private async request<S extends z.ZodTypeAny>(
    method: string,
    path: string,
    body: unknown,
    schema: S,
  ): Promise<z.output<S>> {
    const init: RequestInit = { method, headers: { Accept: 'application/json' } }
    if (body !== undefined) {
      init.headers = { ...init.headers, 'Content-Type': 'application/json' }
      init.body = JSON.stringify(body)
    }

    const response = await fetch(this.url(path), init)
    return this.decode(method, path, response, schema)
  }

  /** Everything that happens to a response, whatever sent the request: the
   *  non-2xx to `ApiError`, and the body to the schema. Shared by `request`
   *  and `postForm` so a multipart upload reports a failure in exactly the
   *  same words as every other call. */
  private async decode<S extends z.ZodTypeAny>(
    method: string,
    path: string,
    response: Response,
    schema: S,
  ): Promise<z.output<S>> {
    const raw = await response.text()
    const parsed = parseJson(raw)

    if (!response.ok) {
      if (response.status === 401 && !this.reportedUnauthorized) {
        this.reportedUnauthorized = true
        this.onUnauthorized?.()
      }
      throw new ApiError(detailOf(parsed, raw, response), response.status)
    }

    const result = schema.safeParse(parsed)
    if (!result.success) {
      throw new ContractError(
        `${method} ${path} answered a shape this build does not understand`,
        formatIssues(result.error),
      )
    }
    // Zod 4 narrows `data` to `z.output<S>` on the success branch by itself.
    // Under Zod 3 this needed an assertion here.
    return result.data
  }
}

const parseJson = (raw: string): unknown => {
  if (!raw) return null
  try {
    return JSON.parse(raw) as unknown
  } catch {
    return null
  }
}

/** FastAPI puts the useful part in `detail`; fall back through the raw body to
 *  the status line, so an error always says *something* actionable. */
const detailOf = (parsed: unknown, raw: string, response: Response): string => {
  if (parsed && typeof parsed === 'object') {
    const record = parsed as Record<string, unknown>
    const detail = record['detail'] ?? record['error']
    if (typeof detail === 'string' && detail) return detail
  }
  if (raw) return raw.length > 200 ? `${raw.slice(0, 199)}…` : raw
  return `${response.status} ${response.statusText}`
}

const formatIssues = (error: z.ZodError): string =>
  error.issues
    .slice(0, 5)
    .map((issue) => `${issue.path.join('.') || '(root)'}: ${issue.message}`)
    .join('; ')

/** Path segments carrying a UUID, a name or a filesystem path all need
 *  encoding, and forgetting on the last one is how a path with a space becomes
 *  a 404 nobody can reproduce. */
export const seg = (value: string | number): string => encodeURIComponent(String(value))

export const query = (
  params: Readonly<Record<string, string | number | null | undefined>>,
): string => {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue
    search.set(key, String(value))
  }
  const rendered = search.toString()
  return rendered ? `?${rendered}` : ''
}
