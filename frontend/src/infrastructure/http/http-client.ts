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
  constructor(private readonly baseUrl: string = '') {}

  // Generic over the *schema* rather than over a result type: several of these
  // shapes carry transforms, so their input and output types differ, and
  // `z.ZodType<T>` would unify both onto T and silently hand back the input.
  get<S extends z.ZodTypeAny>(path: string, schema: S): Promise<z.output<S>> {
    return this.request('GET', path, undefined, schema)
  }

  post<S extends z.ZodTypeAny>(path: string, body: unknown, schema: S): Promise<z.output<S>> {
    return this.request('POST', path, body ?? {}, schema)
  }

  delete<S extends z.ZodTypeAny>(path: string, schema: S): Promise<z.output<S>> {
    return this.request('DELETE', path, undefined, schema)
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

    const response = await fetch(`${this.baseUrl}${path}`, init)
    const raw = await response.text()
    const parsed = parseJson(raw)

    if (!response.ok) {
      throw new ApiError(detailOf(parsed, raw, response), response.status)
    }

    const result = schema.safeParse(parsed)
    if (!result.success) {
      throw new ContractError(
        `${method} ${path} answered a shape this build does not understand`,
        formatIssues(result.error),
      )
    }
    // Zod types `data` as `any` on a generic schema; the narrowing is the
    // `safeParse` above, and this is the one place that has to say so.
    return result.data as z.output<S>
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
