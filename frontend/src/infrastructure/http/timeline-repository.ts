import type { TimelineRepository, TimelineWindowQuery } from '@application/ports/repositories.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, query, seg } from './http-client.ts'
import { toTimeline } from './mappers.ts'

export class HttpTimelineRepository implements TimelineRepository {
  constructor(private readonly http: HttpClient) {}

  async timeline(projectId: ProjectId, window: TimelineWindowQuery = {}) {
    const body = await this.http.get(
      // `from`/`to` are the wire names. The route's parameter is `from_`
      // because `from` is a Python keyword, and FastAPI's `Query(alias=...)`
      // is what reconciles the two -- a client sending `from_` would get the
      // whole timeline back with nothing saying its window was ignored.
      //
      // `limit` is passed through where it used to be omitted. The server's
      // own cap is still the ceiling and still what `truncated` reports; this
      // only lets a caller ask for less.
      `/api/projects/${seg(projectId)}/timeline${query({
        entity_type: window.entityType,
        from: window.from,
        to: window.to,
        limit: window.limit,
      })}`,
      dto.timelineDto,
    )
    return toTimeline(body)
  }
}
