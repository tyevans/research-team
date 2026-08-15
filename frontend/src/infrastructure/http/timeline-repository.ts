import type { TimelineRepository } from '@application/ports/repositories.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, query, seg } from './http-client.ts'
import { toTimeline } from './mappers.ts'

export class HttpTimelineRepository implements TimelineRepository {
  constructor(private readonly http: HttpClient) {}

  async timeline(projectId: ProjectId, entityType?: string) {
    // No `limit`, matching `HttpGraphRepository.whole`: the server's own cap
    // is the right one, and a number picked here would be a second bound to
    // keep in step with it.
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/timeline${query({ entity_type: entityType })}`,
      dto.timelineDto,
    )
    return toTimeline(body)
  }
}
