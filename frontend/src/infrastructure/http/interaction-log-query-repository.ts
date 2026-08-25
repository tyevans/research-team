import type {
  InteractionLogRepository,
  InteractionWindow,
} from '@application/ports/repositories.ts'
import type { InteractionFilters } from '@domain/interaction/filters.ts'
import type { BrowserSessionId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'
import {
  toBrowserSessionPage,
  toInteractionLogHealth,
  toInteractionPage,
  toInteractionSummary,
  toLoggedInteraction,
} from './mappers.ts'

const BASE = '/api/interactions'

/** The reader for the interaction log.
 *
 * A separate object from `HttpInteractionSink` in
 * `interaction-log-repository.ts`, which POSTs and is untouched by this
 * feature. The spec's reason, and it holds: a sink that also reads has two
 * reasons to change, and the sink's deliberate swallowing of every error --
 * correct for telemetry that is droppable by design -- would be the worst
 * possible behaviour on a debugging surface, where a failed fetch must be
 * visible.
 *
 * Every route here is a GET. There is no write side to this class at all,
 * including no truncate: the documented reset is `rm
 * ~/.research-team/interactions.db`, and a destructive route on a port with no
 * authentication buys convenience and costs the whole log.
 */
export class HttpInteractionLogRepository implements InteractionLogRepository {
  constructor(private readonly http: HttpClient) {}

  async health() {
    return toInteractionLogHealth(await this.http.get(`${BASE}/health`, dto.interactionHealthDto))
  }

  async sessions(filters: InteractionFilters, window?: InteractionWindow) {
    // Only the four axes `/sessions` understands. `kinds` and `views` are
    // dropped rather than sent: the server ignores a parameter it does not
    // know and answers the *unfiltered* question, so sending them would put a
    // narrowed filter bar above an unnarrowed list with nothing to tell them
    // apart. `order` is dropped for the same reason -- the route is newest
    // first and takes no ordering.
    const search = new URLSearchParams()
    scope(search, filters, { include: ['install', 'project', 'time'] })
    page(search, window)
    return toBrowserSessionPage(
      await this.http.get(`${BASE}/sessions${render(search)}`, dto.browserSessionPageDto),
    )
  }

  async session(id: BrowserSessionId) {
    const body = await this.http.get(
      `${BASE}/sessions/${seg(id)}`,
      // Its own schema, not the paged one: this route does not page, and a
      // shape with `total` defaulted to 0 would read a paging regression as a
      // session with no events.
      dto.interactionStreamDto,
    )
    return body.events.map(toLoggedInteraction)
  }

  async events(filters: InteractionFilters, window?: InteractionWindow) {
    const search = new URLSearchParams()
    scope(search, filters, { include: ['kind', 'view', 'install', 'project', 'session', 'time'] })
    page(search, window)
    if (window?.order !== undefined) search.set('order', window.order)
    return toInteractionPage(
      await this.http.get(`${BASE}/events${render(search)}`, dto.interactionEventPageDto),
    )
  }

  async summary(filters: InteractionFilters) {
    const search = new URLSearchParams()
    scope(search, filters, { include: ['kind', 'view', 'install', 'project', 'session', 'time'] })
    return toInteractionSummary(
      await this.http.get(`${BASE}/summary${render(search)}`, dto.interactionSummaryDto),
    )
  }
}

type Axis = 'kind' | 'view' | 'install' | 'project' | 'session' | 'time'

/** `filters` onto `search`, one parameter per value.
 *
 * **`append` and not `set` for `kind` and `view`, and that is the whole reason
 * this function exists rather than `http-client.ts`'s `query`.** FastAPI reads
 * a repeatable parameter as `?kind=A&kind=B`; a comma-joined `?kind=A,B`
 * arrives as one string named `A,B`, which matches no kind, filters the feed
 * to nothing, and looks exactly like a window in which nothing happened. It is
 * the precise place a client and a server disagree without either failing, and
 * `interaction-log-query-repository.test.ts` pins it.
 *
 * `include` rather than a single serialiser for every route, because the two
 * routes accept different sets and a parameter the server does not know is
 * ignored silently -- see `sessions` above.
 */
const scope = (
  search: URLSearchParams,
  filters: InteractionFilters,
  options: { readonly include: readonly Axis[] },
): void => {
  const wants = (axis: Axis) => options.include.includes(axis)

  if (wants('kind')) for (const kind of filters.kinds) search.append('kind', kind)
  if (wants('view')) for (const view of filters.views) search.append('view', view)
  if (wants('project') && filters.projectId !== null) search.set('project_id', filters.projectId)
  if (wants('install') && filters.installId !== null) search.set('install_id', filters.installId)
  if (wants('session') && filters.browserSessionId !== null) {
    search.set('browser_session_id', filters.browserSessionId)
  }
  if (wants('time') && filters.since !== null) search.set('since', filters.since)
  if (wants('time') && filters.until !== null) search.set('until', filters.until)
}

/** `limit` and `offset`, omitted when unasked.
 *
 * Omitted rather than sent at the server's own default, so an unwindowed
 * request is byte-identical to what the bare route would have been -- a cache
 * or a log line keyed on the URL keeps meaning what it meant, which is the
 * same reasoning `HttpOntologyRepository` states for its two levers. */
const page = (search: URLSearchParams, window?: InteractionWindow): void => {
  if (window?.limit !== undefined) search.set('limit', String(window.limit))
  if (window?.offset !== undefined) search.set('offset', String(window.offset))
}

const render = (search: URLSearchParams): string => {
  const rendered = search.toString()
  return rendered ? `?${rendered}` : ''
}
